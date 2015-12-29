import sys
import os
import hashlib
import re
import subprocess
import random
import shutil
import zipfile

from datetime import datetime
import arrow

from io import BytesIO

import html5lib
from urllib.parse import urljoin

from PyQt5.QtCore import Qt, QTimer, QUrl, QFileInfo
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QStatusBar, QGridLayout, QGroupBox, QMainWindow,
    QVBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QToolButton,
    QProgressBar, QButtonGroup, QRadioButton)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest

from cddagl.config import (
    get_config_value, set_config_value, new_version, get_build_from_sha256,
    new_build)

READ_BUFFER_SIZE = 16384

BASE_URLS = {
    'Tiles': {
        'Windows x64': 'http://dev.narc.ro/cataclysm/jenkins-latest/Windows_x64/Tiles/',
        'Windows x86': 'http://dev.narc.ro/cataclysm/jenkins-latest/Windows/Tiles/'
    },
    'Console': {
        'Windows x64': 'http://dev.narc.ro/cataclysm/jenkins-latest/Windows_x64/Curses/',
        'Windows x86': 'http://dev.narc.ro/cataclysm/jenkins-latest/Windows/Curses/'
    }
}

def clean_qt_path(path):
    return path.replace('/', '\\')

def is_64_windows():
    return 'PROGRAMFILES(X86)' in os.environ

def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)

class MainWindow(QMainWindow):
    def __init__(self, title):
        super(MainWindow, self).__init__()

        self.setMinimumSize(400, 0)
        width = int(get_config_value('window.width', -1))
        height = int(get_config_value('window.height', -1))
        if width != -1 and height != -1:
            self.resize(width, height)
        
        self.create_status_bar()
        self.create_central_widget()

        self.setWindowTitle(title)

    def create_status_bar(self):
        status_bar = self.statusBar()
        status_bar.busy = 0

        status_bar.showMessage('Ready')

    def create_central_widget(self):
        central_widget = CentralWidget()
        self.setCentralWidget(central_widget)

    def resizeEvent(self, event):
        set_config_value('window.width', event.size().width())
        set_config_value('window.height', event.size().height())


class CentralWidget(QWidget):
    def __init__(self):
        super(CentralWidget, self).__init__()

        game_dir_group_box = GameDirGroupBox()
        self.game_dir_group_box = game_dir_group_box

        update_group_box = UpdateGroupBox()
        self.update_group_box = update_group_box

        layout = QVBoxLayout()
        layout.addWidget(game_dir_group_box)
        layout.addWidget(update_group_box)
        self.setLayout(layout)

    def get_main_window(self):
        return self.parentWidget()


class GameDirGroupBox(QGroupBox):
    def __init__(self):
        super(GameDirGroupBox, self).__init__()

        self.shown = False

        layout = QGridLayout()

        dir_label = QLabel()
        dir_label.setText('Directory:')
        layout.addWidget(dir_label, 0, 0, Qt.AlignRight)
        self.dir_label = dir_label

        dir_edit = QLineEdit()
        dir_edit.editingFinished.connect(self.game_directory_changed)
        layout.addWidget(dir_edit, 0, 1)
        self.dir_edit = dir_edit

        dir_change_button = QToolButton()
        dir_change_button.setText('...')
        dir_change_button.clicked.connect(self.set_game_directory)
        layout.addWidget(dir_change_button, 0, 2)
        self.dir_change_button = dir_change_button

        version_label = QLabel()
        version_label.setText('Version:')
        layout.addWidget(version_label, 1, 0, Qt.AlignRight)
        self.version_label = version_label

        version_value_label = QLabel()
        layout.addWidget(version_value_label, 1, 1)
        self.version_value_label = version_value_label

        build_label = QLabel()
        build_label.setText('Build:')
        layout.addWidget(build_label, 2, 0, Qt.AlignRight)
        self.build_label = build_label

        build_value_label = QLabel()
        build_value_label.setText('Unknown')
        layout.addWidget(build_value_label, 2, 1)
        self.build_value_label = build_value_label

        launch_game_button = QPushButton()
        launch_game_button.setText('Launch game')
        launch_game_button.setEnabled(False)
        launch_game_button.setStyleSheet("font-size: 20px;")
        launch_game_button.clicked.connect(self.launch_game)
        layout.addWidget(launch_game_button, 3, 0, 1, 3)
        self.launch_game_button = launch_game_button

        self.setTitle('Game directory')
        self.setLayout(layout)

    def showEvent(self, event):
        if not self.shown:
            game_directory = get_config_value('game_directory')
            if game_directory is None:
                cddagl_path = os.path.dirname(os.path.realpath(sys.argv[0]))
                default_dir = os.path.join(cddagl_path, 'cdda')
                game_directory = default_dir

            self.last_game_directory = None
            self.dir_edit.setText(game_directory)
            self.game_directory_changed()

        self.shown = True

    def disable_controls(self):
        self.launch_game_button.setEnabled(False)
        self.dir_edit.setEnabled(False)
        self.dir_change_button.setEnabled(False)

    def enable_controls(self):
        self.launch_game_button.setEnabled(True)
        self.dir_edit.setEnabled(True)
        self.dir_change_button.setEnabled(True)

    def launch_game(self):
        self.get_main_window().setWindowState(Qt.WindowMinimized)
        exe_dir = os.path.dirname(self.exe_path)
        subprocess.call(['start', '/D', exe_dir, self.exe_path], shell=True)
        self.get_main_window().close()

    def get_central_widget(self):
        return self.parentWidget()

    def get_main_window(self):
        return self.get_central_widget().get_main_window()

    def set_game_directory(self):
        options = QFileDialog.DontResolveSymlinks | QFileDialog.ShowDirsOnly
        directory = QFileDialog.getExistingDirectory(self,
                'Game directory', self.dir_edit.text(), options=options)
        if directory:
            self.dir_edit.setText(clean_qt_path(directory))
            self.game_directory_changed()

    def game_directory_changed(self):
        directory = self.dir_edit.text()
        self.exe_path = None
        
        central_widget = self.get_central_widget()
        update_group_box = central_widget.update_group_box

        if not os.path.isdir(directory):
            self.version_value_label.setText('Not a valid directory')
        else:
            # Find the executable
            console_exe = os.path.join(directory, 'cataclysm.exe')
            tiles_exe = os.path.join(directory, 'cataclysm-tiles.exe')

            exe_path = None
            version_type = None
            if os.path.isfile(console_exe):
                version_type = 'console'
                exe_path = console_exe
            elif os.path.isfile(tiles_exe):
                version_type = 'tiles'
                exe_path = tiles_exe

            if version_type is None:
                self.version_value_label.setText('Not a CDDA directory')
            else:
                self.exe_path = exe_path
                self.version_type = version_type
                if self.last_game_directory != directory:
                    self.update_version()

        if self.exe_path is None:
            self.launch_game_button.setEnabled(False)
            update_group_box.update_button.setText('Install game')
        else:
            self.launch_game_button.setEnabled(True)
            update_group_box.update_button.setText('Update game')

        self.last_game_directory = directory
        set_config_value('game_directory', directory)

    def update_version(self):
        main_window = self.get_main_window()

        status_bar = main_window.statusBar()
        status_bar.clearMessage()

        status_bar.busy += 1

        reading_label = QLabel()
        reading_label.setText('Reading: {0}'.format(self.exe_path))
        status_bar.addWidget(reading_label, 100)
        self.reading_label = reading_label

        progress_bar = QProgressBar()
        status_bar.addWidget(progress_bar)
        self.reading_progress_bar = progress_bar

        timer = QTimer(self)
        self.exe_reading_timer = timer

        exe_size = os.path.getsize(self.exe_path)

        progress_bar.setRange(0, exe_size)
        self.exe_total_read = 0

        self.exe_sha256 = hashlib.sha256()
        self.last_bytes = None
        self.game_version = 'Unknown'
        self.opened_exe = open(self.exe_path, 'rb')

        def timeout():
            bytes = self.opened_exe.read(READ_BUFFER_SIZE)
            if len(bytes) == 0:
                self.opened_exe.close()
                self.exe_reading_timer.stop()
                main_window = self.get_main_window()
                status_bar = main_window.statusBar()

                self.version_value_label.setText(
                    '{version} ({type})'.format(version=self.game_version,
                    type=self.version_type))

                status_bar.removeWidget(self.reading_label)
                status_bar.removeWidget(self.reading_progress_bar)

                status_bar.busy -= 1
                if status_bar.busy == 0:
                    status_bar.showMessage('Ready')

                sha256 = self.exe_sha256.hexdigest()

                new_version(self.game_version, sha256)

                build = get_build_from_sha256(sha256)

                if build is not None:
                    build_date = arrow.get(build['released_on'], 'UTC')
                    human_delta = build_date.humanize(arrow.utcnow())
                    self.build_value_label.setText('{0} ({1})'.format(
                        build['build'], human_delta))

            else:
                last_frame = bytes
                if self.last_bytes is not None:
                    last_frame = self.last_bytes + last_frame

                match = re.search(
                    b'(?P<version>[01]\\.[A-F](-\\d+-g[0-9a-f]+)?)\\x00',
                    last_frame)
                if match is not None:
                    game_version = match.group('version').decode('ascii')
                    self.game_version = game_version
                    self.version_value_label.setText(
                        '{version} ({type})'.format(version=self.game_version,
                            type=self.version_type))

                self.exe_total_read += len(bytes)
                self.reading_progress_bar.setValue(self.exe_total_read)
                self.exe_sha256.update(bytes)
                self.last_bytes = bytes

        timer.timeout.connect(timeout)
        timer.start(0)

        '''from PyQt5.QtCore import pyqtRemoveInputHook, pyqtRestoreInputHook
        pyqtRemoveInputHook()
        import pdb; pdb.set_trace()
        pyqtRestoreInputHook()'''

    def analyse_new_build(self, build):
        game_dir = self.dir_edit.text()

        console_exe = os.path.join(game_dir, 'cataclysm.exe')
        tiles_exe = os.path.join(game_dir, 'cataclysm-tiles.exe')

        exe_path = None
        version_type = None
        if os.path.isfile(console_exe):
            version_type = 'console'
            exe_path = console_exe
        elif os.path.isfile(tiles_exe):
            version_type = 'tiles'
            exe_path = tiles_exe

        if version_type is None:
            self.version_value_label.setText('Not a CDDA directory')
        else:
            self.exe_path = exe_path
            self.version_type = version_type
            self.build_number = build['number']
            self.build_date = build['date']

            main_window = self.get_main_window()

            status_bar = main_window.statusBar()
            status_bar.clearMessage()

            status_bar.busy += 1

            reading_label = QLabel()
            reading_label.setText('Reading: {0}'.format(self.exe_path))
            status_bar.addWidget(reading_label, 100)
            self.reading_label = reading_label

            progress_bar = QProgressBar()
            status_bar.addWidget(progress_bar)
            self.reading_progress_bar = progress_bar

            timer = QTimer(self)
            self.exe_reading_timer = timer

            exe_size = os.path.getsize(self.exe_path)

            progress_bar.setRange(0, exe_size)
            self.exe_total_read = 0

            self.exe_sha256 = hashlib.sha256()
            self.last_bytes = None
            self.game_version = 'Unknown'
            self.opened_exe = open(self.exe_path, 'rb')

            def timeout():
                bytes = self.opened_exe.read(READ_BUFFER_SIZE)
                if len(bytes) == 0:
                    self.opened_exe.close()
                    self.exe_reading_timer.stop()
                    main_window = self.get_main_window()
                    status_bar = main_window.statusBar()

                    self.version_value_label.setText(
                        '{version} ({type})'.format(version=self.game_version,
                        type=self.version_type))
                    build_date = arrow.get(self.build_date, 'UTC')
                    human_delta = build_date.humanize(arrow.utcnow())
                    self.build_value_label.setText('{0} ({1})'.format(
                        self.build_number, human_delta))

                    status_bar.removeWidget(self.reading_label)
                    status_bar.removeWidget(self.reading_progress_bar)

                    status_bar.busy -= 1

                    sha256 = self.exe_sha256.hexdigest()

                    new_build(self.game_version, sha256, self.build_number,
                        self.build_date)

                    central_widget = self.get_central_widget()
                    update_group_box = central_widget.update_group_box

                    update_group_box.post_extraction()

                else:
                    last_frame = bytes
                    if self.last_bytes is not None:
                        last_frame = self.last_bytes + last_frame

                    match = re.search(
                        b'(?P<version>[01]\\.[A-F](-\\d+-g[0-9a-f]+)?)\\x00',
                        last_frame)
                    if match is not None:
                        game_version = match.group('version').decode('ascii')
                        self.game_version = game_version
                        self.version_value_label.setText(
                            '{version} ({type})'.format(
                                version=self.game_version,
                                type=self.version_type))

                    self.exe_total_read += len(bytes)
                    self.reading_progress_bar.setValue(self.exe_total_read)
                    self.exe_sha256.update(bytes)
                    self.last_bytes = bytes

            timer.timeout.connect(timeout)
            timer.start(0)


class UpdateGroupBox(QGroupBox):
    def __init__(self):
        super(UpdateGroupBox, self).__init__()

        self.shown = False
        self.updating = False

        self.qnam = QNetworkAccessManager()
        self.http_reply = None

        layout = QGridLayout()

        graphics_label = QLabel()
        graphics_label.setText('Graphics:')
        layout.addWidget(graphics_label, 0, 0, Qt.AlignRight)
        self.graphics_label = graphics_label

        graphics_button_group = QButtonGroup()
        self.graphics_button_group = graphics_button_group

        tiles_radio_button = QRadioButton()
        tiles_radio_button.setText('Tiles')
        layout.addWidget(tiles_radio_button, 0, 1)
        self.tiles_radio_button = tiles_radio_button
        graphics_button_group.addButton(tiles_radio_button)

        console_radio_button = QRadioButton()
        console_radio_button.setText('Console')
        layout.addWidget(console_radio_button, 0, 2)
        self.console_radio_button = console_radio_button
        graphics_button_group.addButton(console_radio_button)

        graphics_button_group.buttonClicked.connect(self.graphics_clicked)

        platform_label = QLabel()
        platform_label.setText('Platform:')
        layout.addWidget(platform_label, 1, 0, Qt.AlignRight)
        self.platform_label = platform_label

        platform_button_group = QButtonGroup()
        self.platform_button_group = platform_button_group

        x64_radio_button = QRadioButton()
        x64_radio_button.setText('Windows x64')
        layout.addWidget(x64_radio_button, 1, 1)
        self.x64_radio_button = x64_radio_button
        platform_button_group.addButton(x64_radio_button)

        platform_button_group.buttonClicked.connect(self.platform_clicked)

        if not is_64_windows():
            x64_radio_button.setEnabled(False)

        x86_radio_button = QRadioButton()
        x86_radio_button.setText('Windows x86')
        layout.addWidget(x86_radio_button, 1, 2)
        self.x86_radio_button = x86_radio_button
        platform_button_group.addButton(x86_radio_button)

        latest_build_label = QLabel()
        latest_build_label.setText('Latest build:')
        layout.addWidget(latest_build_label, 2, 0, Qt.AlignRight)
        self.latest_build_label = latest_build_label

        latest_build_value_label = QLabel()
        latest_build_value_label.setText('Unknown')
        layout.addWidget(latest_build_value_label, 2, 1, 1, 2)
        self.latest_build_value_label = latest_build_value_label

        update_button = QPushButton()
        update_button.setText('Update game')
        update_button.setEnabled(False)
        update_button.clicked.connect(self.update_game)
        layout.addWidget(update_button, 3, 0, 1, 3)
        self.update_button = update_button

        self.setTitle('Update/Installation')
        self.setLayout(layout)

    def showEvent(self, event):
        if not self.shown:
            graphics = get_config_value('graphics')
            if graphics is None:
                graphics = 'Tiles'

            platform = get_config_value('platform')
            if platform is None:
                if is_64_windows():
                    platform = 'Windows x64'
                else:
                    platform = 'Windows x86'

            if graphics == 'Tiles':
                self.tiles_radio_button.setChecked(True)
            elif graphics == 'Console':
                self.console_radio_button.setChecked(True)

            if platform == 'Windows x64':
                self.x64_radio_button.setChecked(True)
            elif platform == 'Windows x86':
                self.x86_radio_button.setChecked(True)

            self.lb_html = BytesIO()
            self.start_lb_request(BASE_URLS[graphics][platform])

        self.shown = True

    def update_game(self):
        if not self.updating:
            self.updating = True
            self.download_aborted = False
            self.backing_up_game = False
            self.extracting_new_build = False

            central_widget = self.get_central_widget()
            game_dir_group_box = central_widget.game_dir_group_box

            game_dir_group_box.disable_controls()
            self.disable_radio_buttons()

            game_dir = game_dir_group_box.dir_edit.text()

            try:
                if not os.path.isdir(game_dir):
                    os.makedirs(game_dir)

                temp_dir = os.path.join(os.environ['TEMP'],
                    'CDDA Game Launcher')
                if not os.path.isdir(temp_dir):
                    os.makedirs(temp_dir)
                
                download_dir = os.path.join(temp_dir, 'newbuild')
                while os.path.isdir(download_dir):
                    download_dir = os.path.join(temp_dir, 'newbuild-{0}'.format(
                        '%08x' % random.randrange(16**8)))
                os.makedirs(download_dir)

                download_url = self.last_build['url']
                
                url = QUrl(download_url)
                file_info = QFileInfo(url.path())
                file_name = file_info.fileName()

                self.downloaded_file = os.path.join(download_dir, file_name)
                self.downloading_file = open(self.downloaded_file, 'wb')

                self.download_game_update(download_url)

            except OSError as e:
                main_window = self.get_main_window()
                status_bar = main_window.statusBar()

                status_bar.showMessage(str(e))

                self.finish_updating()
        else:
            # Are we downloading the file?
            if self.download_http_reply.isRunning():
                self.download_aborted = True
                self.download_http_reply.abort()

                central_widget = self.get_central_widget()
                game_dir_group_box = central_widget.game_dir_group_box

                main_window = self.get_main_window()

                status_bar = main_window.statusBar()

                if game_dir_group_box.exe_path is not None:
                    self.update_button.setText('Update game')
                    if status_bar.busy == 0:
                        status_bar.showMessage('Update cancelled')
                else:
                    self.update_button.setText('Install game')

                    if status_bar.busy == 0:
                        status_bar.showMessage('Installation cancelled')

            self.finish_updating()

    def get_central_widget(self):
        return self.parentWidget()

    def get_main_window(self):
        return self.get_central_widget().get_main_window()

    def disable_radio_buttons(self):
        self.tiles_radio_button.setEnabled(False)
        self.console_radio_button.setEnabled(False)
        self.x64_radio_button.setEnabled(False)
        self.x86_radio_button.setEnabled(False)

    def enable_radio_buttons(self):
        self.tiles_radio_button.setEnabled(True)
        self.console_radio_button.setEnabled(True)
        if is_64_windows():
            self.x64_radio_button.setEnabled(True)
        self.x86_radio_button.setEnabled(True)

    def download_game_update(self, url):
        main_window = self.get_main_window()

        status_bar = main_window.statusBar()
        status_bar.clearMessage()

        status_bar.busy += 1

        downloading_label = QLabel()
        downloading_label.setText('Downloading: {0}'.format(url))
        status_bar.addWidget(downloading_label, 100)
        self.downloading_label = downloading_label

        dowloading_speed_label = QLabel()
        status_bar.addWidget(dowloading_speed_label)
        self.dowloading_speed_label = dowloading_speed_label

        progress_bar = QProgressBar()
        status_bar.addWidget(progress_bar)
        self.downloading_progress_bar = progress_bar
        progress_bar.setMinimum(0)

        self.download_last_read = datetime.utcnow()
        self.download_last_bytes_read = 0
        self.download_speed_count = 0

        self.download_http_reply = self.qnam.get(QNetworkRequest(QUrl(url)))
        self.download_http_reply.finished.connect(self.download_http_finished)
        self.download_http_reply.readyRead.connect(
            self.download_http_ready_read)
        self.download_http_reply.downloadProgress.connect(
            self.download_dl_progress)

        central_widget = self.get_central_widget()
        game_dir_group_box = central_widget.game_dir_group_box

        if game_dir_group_box.exe_path is not None:
            self.update_button.setText('Cancel update')
        else:
            self.update_button.setText('Cancel installation')

    def download_http_finished(self):
        self.downloading_file.close()

        main_window = self.get_main_window()

        status_bar = main_window.statusBar()
        status_bar.removeWidget(self.downloading_label)
        status_bar.removeWidget(self.dowloading_speed_label)
        status_bar.removeWidget(self.downloading_progress_bar)

        status_bar.busy -= 1

        if self.download_aborted:
            download_dir = os.path.dirname(self.downloaded_file)
            shutil.rmtree(download_dir)
        else:
            self.backup_current_game()

    def backup_current_game(self):
        self.backing_up_game = True

        central_widget = self.get_central_widget()
        game_dir_group_box = central_widget.game_dir_group_box

        game_dir = game_dir_group_box.dir_edit.text()

        main_window = self.get_main_window()
        status_bar = main_window.statusBar()

        backup_dir = os.path.join(game_dir, 'previous_version')
        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir)

        dir_list = os.listdir(game_dir)
        self.backup_dir_list = dir_list

        if len(dir_list) > 0:
            status_bar.busy += 1

            backup_label = QLabel()
            status_bar.addWidget(backup_label, 100)
            self.backup_label = backup_label

            progress_bar = QProgressBar()
            status_bar.addWidget(progress_bar)
            self.backup_progress_bar = progress_bar

            timer = QTimer(self)
            self.backup_timer = timer

            progress_bar.setRange(0, len(dir_list))

            os.makedirs(backup_dir)
            self.backup_dir = backup_dir
            self.game_dir = game_dir
            self.backup_index = 0

            def timeout():
                self.backup_progress_bar.setValue(self.backup_index)

                if self.backup_index == len(self.backup_dir_list):
                    self.backup_timer.stop()

                    main_window = self.get_main_window()
                    status_bar = main_window.statusBar()

                    status_bar.removeWidget(self.backup_label)
                    status_bar.removeWidget(self.backup_progress_bar)

                    status_bar.busy -= 1

                    self.backing_up_game = False
                    self.extract_new_build()

                else:
                    backup_element = self.backup_dir_list[self.backup_index]
                    self.backup_label.setText('Backing up {0}'.format(
                        backup_element))
                    
                    shutil.move(os.path.join(self.game_dir, backup_element),
                        self.backup_dir)

                    self.backup_index += 1

            timer.timeout.connect(timeout)
            timer.start(0)
        else:
            self.backing_up_game = False
            self.extract_new_build()

    def extract_new_build(self):
        self.extracting_new_build = True
        
        z = zipfile.ZipFile(self.downloaded_file)
        self.extracting_zipfile = z

        self.extracting_infolist = z.infolist()
        self.extracting_index = 0

        main_window = self.get_main_window()
        status_bar = main_window.statusBar()

        status_bar.busy += 1

        extracting_label = QLabel()
        status_bar.addWidget(extracting_label, 100)
        self.extracting_label = extracting_label

        progress_bar = QProgressBar()
        status_bar.addWidget(progress_bar)
        self.extracting_progress_bar = progress_bar

        timer = QTimer(self)
        self.extracting_timer = timer

        progress_bar.setRange(0, len(self.extracting_infolist))

        def timeout():
            self.extracting_progress_bar.setValue(self.extracting_index)

            if self.extracting_index == len(self.extracting_infolist):
                self.extracting_timer.stop()

                main_window = self.get_main_window()
                status_bar = main_window.statusBar()

                status_bar.removeWidget(self.extracting_label)
                status_bar.removeWidget(self.extracting_progress_bar)

                status_bar.busy -= 1

                self.extracting_new_build = False

                self.extracting_zipfile.close()

                download_dir = os.path.dirname(self.downloaded_file)
                shutil.rmtree(download_dir)

                central_widget = self.get_central_widget()
                game_dir_group_box = central_widget.game_dir_group_box

                game_dir_group_box.analyse_new_build(self.last_build)

            else:
                extracting_element = self.extracting_infolist[
                    self.extracting_index]
                self.extracting_label.setText('Extracting {0}'.format(
                    extracting_element.filename))
                
                self.extracting_zipfile.extract(extracting_element,
                    self.game_dir)

                self.extracting_index += 1

        timer.timeout.connect(timeout)
        timer.start(0)

    def post_extraction(self):
        main_window = self.get_main_window()
        status_bar = main_window.statusBar()

        # Copy config, save, templates and memorial directory from previous version
        previous_version_dir = os.path.join(self.game_dir, 'previous_version')
        if os.path.isdir(previous_version_dir):

            previous_dirs = ('config', 'save', 'templates', 'memorial')
            for previous_dir in previous_dirs:
                previous_dir_path = os.path.join(previous_version_dir,
                    previous_dir)

                if os.path.isdir(previous_dir_path):
                    status_bar.showMessage(
                        'Restoring {0} directory from previous version'.format(
                            previous_dir))
                    dst_dir = os.path.join(self.game_dir, previous_dir)
                    shutil.copytree(previous_dir_path, dst_dir)

        # Copy custom tilesets, mods and soundpack from previous version
        
        self.finish_updating()

    def finish_updating(self):
        self.updating = False
        central_widget = self.get_central_widget()
        game_dir_group_box = central_widget.game_dir_group_box

        game_dir_group_box.enable_controls()
        self.enable_radio_buttons()

    def download_http_ready_read(self):
        self.downloading_file.write(self.download_http_reply.readAll())

    def download_dl_progress(self, bytes_read, total_bytes):
        self.downloading_progress_bar.setMaximum(total_bytes)
        self.downloading_progress_bar.setValue(bytes_read)

        self.download_speed_count += 1

        if self.download_speed_count % 5 == 0:
            delta_bytes = bytes_read - self.download_last_bytes_read
            delta_time = datetime.utcnow() - self.download_last_read

            bytes_secs = delta_bytes / delta_time.total_seconds()
            self.dowloading_speed_label.setText('{0}/s'.format(
                sizeof_fmt(bytes_secs)))

            self.download_last_bytes_read = bytes_read
            self.download_last_read = datetime.utcnow()

    def start_lb_request(self, url):
        self.disable_radio_buttons()

        main_window = self.get_main_window()

        status_bar = main_window.statusBar()
        status_bar.clearMessage()

        status_bar.busy += 1

        self.latest_build_value_label.setText('Fetching remote builds')

        fetching_label = QLabel()
        fetching_label.setText('Fetching: {0}'.format(url))
        self.base_url = url
        status_bar.addWidget(fetching_label, 100)
        self.fetching_label = fetching_label

        progress_bar = QProgressBar()
        status_bar.addWidget(progress_bar)
        self.fetching_progress_bar = progress_bar

        progress_bar.setMinimum(0)

        self.http_reply = self.qnam.get(QNetworkRequest(QUrl(url)))
        self.http_reply.finished.connect(self.lb_http_finished)
        self.http_reply.readyRead.connect(self.lb_http_ready_read)
        self.http_reply.downloadProgress.connect(self.lb_dl_progress)

    def lb_http_finished(self):
        main_window = self.get_main_window()

        status_bar = main_window.statusBar()
        status_bar.removeWidget(self.fetching_label)
        status_bar.removeWidget(self.fetching_progress_bar)

        status_bar.busy -= 1
        if status_bar.busy == 0:
            status_bar.showMessage('Ready')

        self.enable_radio_buttons()

        self.lb_html.seek(0)
        document = html5lib.parse(self.lb_html, treebuilder='lxml',
            encoding='utf8', namespaceHTMLElements=False)

        builds = []
        for row in document.getroot().cssselect('tr'):
            build = {}
            for index, cell in enumerate(row.cssselect('td')):
                if index == 1:
                    if len(cell) > 0 and cell[0].text.startswith('cataclysmdda'):
                        anchor = cell[0]
                        url = urljoin(self.base_url, anchor.get('href'))
                        name = anchor.text

                        build_number = None
                        match = re.search(
                            'cataclysmdda-[01]\\.[A-F]-(?P<build>\d+)', name)
                        if match is not None:
                            build_number = match.group('build')

                        build['url'] = url
                        build['name'] = name
                        build['number'] = build_number
                elif index == 2:
                    # build date
                    str_date = cell.text.strip()
                    if str_date != '':
                        build_date = datetime.strptime(str_date,
                            '%Y-%m-%d %H:%M')
                        build['date'] = build_date

            if 'url' in build:
                builds.append(build)

        if len(builds) > 0:
            last_build = builds[-1]
            build_date = arrow.get(last_build['date'], 'UTC')
            human_delta = build_date.humanize(arrow.utcnow())
            self.latest_build_value_label.setText('{number} ({delta})'.format(
                number=last_build['number'], delta=human_delta))

            self.last_build = last_build

            central_widget = self.get_central_widget()
            game_dir_group_box = central_widget.game_dir_group_box

            if game_dir_group_box.exe_path is not None:
                self.update_button.setText('Update game')
            else:
                self.update_button.setText('Install game')

            self.update_button.setEnabled(True)

        else:
            self.latest_build_value_label.setText(
                'Could not find remote builds')

    def lb_http_ready_read(self):
        self.lb_html.write(self.http_reply.readAll())

    def lb_dl_progress(self, bytes_read, total_bytes):
        self.fetching_progress_bar.setMaximum(total_bytes)
        self.fetching_progress_bar.setValue(bytes_read)

    def graphics_clicked(self, button):
        set_config_value('graphics', button.text())

        selected_graphics = self.graphics_button_group.checkedButton().text()
        selected_platform = self.platform_button_group.checkedButton().text()
        url = BASE_URLS[selected_graphics][selected_platform]

        self.start_lb_request(url)

    def platform_clicked(self, button):
        set_config_value('platform', button.text())

        selected_graphics = self.graphics_button_group.checkedButton().text()
        selected_platform = self.platform_button_group.checkedButton().text()
        url = BASE_URLS[selected_graphics][selected_platform]

        self.start_lb_request(url)

def start_ui():
    app = QApplication(sys.argv)
    mainWin = MainWindow('CDDA Game Launcher')
    mainWin.show()
    sys.exit(app.exec_())