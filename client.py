import sys
import datetime
import cv2
import numpy as np
import requests
import pymysql
from PyQt5.QtWidgets import (
    QApplication, QLabel, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QSpacerItem, QSizePolicy, QTableWidget,
    QTableWidgetItem, QDialog, QLineEdit, QMessageBox,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QComboBox
)
from PyQt5.QtGui import (
    QImage, QPixmap, QFont, QPalette, QColor, QIcon, QPainter
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
import jwt
import json
import os

# 设置QT自动缩放
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

class LoginWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('登录')
        self.setWindowIcon(QIcon('icon.png'))
        self.setFixedSize(300, 200)
        
        self.layout = QVBoxLayout()
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText('用户名')
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText('密码')
        self.password_input.setEchoMode(QLineEdit.Password)
        
        self.login_button = QPushButton('登录')
        self.login_button.clicked.connect(self.handle_login)
        
        self.layout.addWidget(self.username_input)
        self.layout.addWidget(self.password_input)
        self.layout.addWidget(self.login_button)
        
        self.setLayout(self.layout)
        
        self.token = None
        self.current_user = None
    
    def handle_login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        
        if not username or not password:
            QMessageBox.warning(self, '错误', '请输入用户名和密码')
            return
        
        try:
            response = requests.post(
                'http://localhost:5000/login',
                json={'username': username, 'password': password}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data['token']
                self.current_user = data['user']
                self.accept()
            else:
                QMessageBox.warning(self, '错误', '登录失败: ' + response.json().get('message', '未知错误'))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'连接服务器失败: {str(e)}')

class VideoStreamThread(QThread):
    frame_received = pyqtSignal(np.ndarray, int, int, int, int)

    def __init__(self, stream_url, token):
        super().__init__()
        self.stream_url = stream_url
        self.token = token
        self.running = True

    def run(self):
        try:
            headers = {'Authorization': self.token}
            stream = requests.get(self.stream_url, stream=True, headers=headers)
            bytes_data = b''

            for chunk in stream.iter_content(chunk_size=1024):
                if not self.running:
                    break
                bytes_data += chunk
                a = bytes_data.find(b'\xff\xd8')
                b = bytes_data.find(b'\xff\xd9')
                if a != -1 and b != -1:
                    jpg = bytes_data[a:b + 2]
                    bytes_data = bytes_data[b + 2:]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)

                    header_end = bytes_data.find(b'\r\n\r\n')
                    if header_end != -1:
                        headers = bytes_data[:header_end].decode('utf-8')
                        bytes_data = bytes_data[header_end + 4:]

                        top = int(self._get_header_value(headers, 'Top'))
                        left = int(self._get_header_value(headers, 'Left'))
                        right = int(self._get_header_value(headers, 'Right'))
                        bottom = int(self._get_header_value(headers, 'Bottom'))

                        self.frame_received.emit(frame, top, left, right, bottom)

        except Exception as e:
            print(f"Client error: {e}")

    def stop(self):
        self.running = False

    def _get_header_value(self, headers, header_name):
        for header in headers.split('\r\n'):
            if header.startswith(header_name):
                return header.split(': ')[1]
        return -1

class MapViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # 加载地图背景
        self.map_pixmap = QPixmap('map.png')
        self.map_item = self.scene.addPixmap(self.map_pixmap)
        
        self.alarm_markers = []
        self.setRenderHint(QPainter.Antialiasing)
        
    def add_alarm_marker(self, x, y, alarm_id):
        marker = QGraphicsEllipseItem(x-5, y-5, 10, 10)
        marker.setBrush(QColor(255, 0, 0))
        marker.setData(0, alarm_id)
        self.scene.addItem(marker)
        self.alarm_markers.append(marker)
        
    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item and item in self.alarm_markers:
            alarm_id = item.data(0)
            self.parent().show_alarm_details(alarm_id)
        super().mousePressEvent(event)

class MainWindow(QWidget):
    def __init__(self, token, current_user):
        super().__init__()
        self.token = token
        self.current_user = current_user
        self.alarm_playing = False
        self.init_ui()

        self.video_thread = VideoStreamThread('http://192.168.51.85:8080', self.token)
        self.video_thread.frame_received.connect(self.update_frame)
        self.video_thread.start()

        self.load_alarms_to_map()

    def init_ui(self):
        self.setWindowTitle('火灾监控系统')
        self.setWindowIcon(QIcon('icon.png'))
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #f0f0f0;
            }
            QLabel#Title {
                font-size: 24px;
                font-weight: bold;
                color: #f0f0f0;
            }
            QLabel#Info {
                font-size: 18px;
            }
            QPushButton {
                background-color: #ff4d4d;
                color: white;
                font-size: 16px;
                border-radius: 8px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #ff6666;
            }
            QPushButton:pressed {
                background-color: #e60000;
            }
        """)

        self.layout = QHBoxLayout()

        # 左侧面板
        left_panel = QVBoxLayout()
        
        self.title_label = QLabel('火灾报警地图')
        self.title_label.setObjectName('Title')
        self.title_label.setAlignment(Qt.AlignCenter)
        
        self.map_viewer = MapViewer()
        self.map_viewer.setFixedSize(600, 400)
        
        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(5)
        self.alarm_table.setHorizontalHeaderLabels(['ID', '时间', '位置', '状态', '操作'])
        self.alarm_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        left_panel.addWidget(self.title_label)
        left_panel.addWidget(self.map_viewer)
        left_panel.addWidget(self.alarm_table)

        # 右侧面板
        right_panel = QVBoxLayout()
        
        self.monitor_title = QLabel('实时监控画面')
        self.monitor_title.setObjectName('Title')
        self.monitor_title.setAlignment(Qt.AlignCenter)
        
        # 用于显示OpenCV帧的QLabel
        self.cv_label = QLabel()
        self.cv_label.setAlignment(Qt.AlignCenter)
        self.cv_label.setStyleSheet("border: 1px solid #f0f0f0;")
        self.cv_label.setFixedSize(640, 480)
        
        # 用于播放报警视频的QVideoWidget
        self.video_widget = QVideoWidget()
        self.video_widget.setFixedSize(640, 480)
        self.video_widget.hide()  # 初始隐藏，只在播放报警视频时显示
        
        self.info_label = QLabel()
        self.info_label.setObjectName('Info')
        self.info_label.setAlignment(Qt.AlignCenter)
        
        self.alarm_button = QPushButton('停止警报')
        self.alarm_button.clicked.connect(self.stop_alarm)
        
        right_panel.addWidget(self.monitor_title)
        right_panel.addWidget(self.cv_label)
        right_panel.addWidget(self.video_widget)
        right_panel.addWidget(self.info_label)
        right_panel.addWidget(self.alarm_button)
        
        if self.current_user['role'] == 'admin':
            self.admin_button = QPushButton('管理面板')
            self.admin_button.clicked.connect(self.show_admin_panel)
            right_panel.addWidget(self.admin_button)

        self.layout.addLayout(left_panel, 60)
        self.layout.addLayout(right_panel, 40)

        self.setLayout(self.layout)
        
        # 初始化媒体播放器
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.stateChanged.connect(self.handle_video_state)

    def handle_video_state(self, state):
        """处理视频播放状态变化"""
        if state == QMediaPlayer.StoppedState:
            self.video_widget.hide()
            self.cv_label.show()

    def load_alarms_to_map(self):
        try:
            headers = {'Authorization': self.token}
            response = requests.get('http://localhost:5000/alarms', headers=headers)
            
            if response.status_code == 200:
                alarms = response.json()
                self.alarm_table.setRowCount(len(alarms))
                
                for i, alarm in enumerate(alarms):
                    x = alarm['left_location']
                    y = alarm['top_location']
                    self.map_viewer.add_alarm_marker(x, y, alarm['id'])
                    
                    self.alarm_table.setItem(i, 0, QTableWidgetItem(str(alarm['id'])))
                    self.alarm_table.setItem(i, 1, QTableWidgetItem(alarm['time']))
                    self.alarm_table.setItem(i, 2, QTableWidgetItem(
                        f"Top: {alarm['top_location']}, Left: {alarm['left_location']}"
                    ))
                    self.alarm_table.setItem(i, 3, QTableWidgetItem("未处理" if i % 2 == 0 else "已处理"))
                    
                    view_btn = QPushButton('查看详情')
                    view_btn.clicked.connect(lambda _, id=alarm['id']: self.show_alarm_details(id))
                    self.alarm_table.setCellWidget(i, 4, view_btn)
                    
        except Exception as e:
            QMessageBox.critical(self, '错误', f'加载报警数据失败: {str(e)}')

    def show_alarm_details(self, alarm_id):
        try:
            headers = {'Authorization': self.token}
            response = requests.get(f'http://localhost:5000/alarms/{alarm_id}/video', headers=headers)
            
            if response.status_code == 200:
                video_path = response.json()['video_path']
                self.cv_label.hide()
                self.video_widget.show()
                self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(video_path)))
                self.media_player.play()
            else:
                QMessageBox.warning(self, '警告', '无法加载报警视频')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'加载报警详情失败: {str(e)}')

    def show_admin_panel(self):
        if self.current_user['role'] == 'admin':
            self.admin_panel = AdminPanel(self.token)
            self.admin_panel.show()

    def update_frame(self, frame, top, left, right, bottom):
        if top != -1 and left != -1 and right != -1 and bottom != -1:
            self.info_label.setText(f"发生火灾! 具体位置： top: {top}, left: {left}, right: {right}, bottom: {bottom}")
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
            
            # 保存报警视频片段
            video_path = f"alarm_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            
            try:
                headers = {'Authorization': self.token, 'Content-Type': 'application/json'}
                data = {
                    'top': top,
                    'left': left,
                    'right': right,
                    'bottom': bottom,
                    'video_path': video_path
                }
                response = requests.post('http://localhost:5000/alarms', headers=headers, json=data)
                
                if response.status_code == 201:
                    self.load_alarms_to_map()
            except Exception as e:
                print(f"Failed to save alarm: {str(e)}")
            
        # 显示OpenCV帧
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.cv_label.setPixmap(QPixmap.fromImage(q_img))

    def stop_alarm(self):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.stop()
        self.info_label.setText("")

    def closeEvent(self, event):
        self.video_thread.stop()
        self.video_thread.wait()
        self.media_player.stop()
        event.accept()

class AdminPanel(QWidget):
    def __init__(self, token):
        super().__init__()
        self.token = token
        self.setWindowTitle('管理员面板')
        self.setFixedSize(800, 600)
        
        self.layout = QVBoxLayout()
        
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(4)
        self.user_table.setHorizontalHeaderLabels(['ID', '用户名', '角色', '操作'])
        self.load_users()
        
        self.add_user_btn = QPushButton('添加用户')
        self.add_user_btn.clicked.connect(self.show_add_user_dialog)
        
        self.layout.addWidget(self.user_table)
        self.layout.addWidget(self.add_user_btn)
        
        self.setLayout(self.layout)
    
    def load_users(self):
        try:
            headers = {'Authorization': self.token}
            response = requests.get('http://localhost:5000/admin/users', headers=headers)
            
            if response.status_code == 200:
                users = response.json()
                self.user_table.setRowCount(len(users))
                
                for i, user in enumerate(users):
                    self.user_table.setItem(i, 0, QTableWidgetItem(str(user['id'])))
                    self.user_table.setItem(i, 1, QTableWidgetItem(user['username']))
                    self.user_table.setItem(i, 2, QTableWidgetItem(user['role']))
                    
                    delete_btn = QPushButton('删除')
                    delete_btn.clicked.connect(lambda _, id=user['id']: self.delete_user(id))
                    self.user_table.setCellWidget(i, 3, delete_btn)
        except Exception as e:
            QMessageBox.critical(self, '错误', f'加载用户数据失败: {str(e)}')
    
    def show_add_user_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('添加用户')
        
        layout = QVBoxLayout()
        
        username_input = QLineEdit()
        username_input.setPlaceholderText('用户名')
        
        password_input = QLineEdit()
        password_input.setPlaceholderText('密码')
        password_input.setEchoMode(QLineEdit.Password)
        
        role_combo = QComboBox()
        role_combo.addItems(['user', 'admin'])
        
        add_btn = QPushButton('添加')
        add_btn.clicked.connect(lambda: self.add_user(
            username_input.text(),
            password_input.text(),
            role_combo.currentText(),
            dialog
        ))
        
        layout.addWidget(username_input)
        layout.addWidget(password_input)
        layout.addWidget(role_combo)
        layout.addWidget(add_btn)
        
        dialog.setLayout(layout)
        dialog.exec_()
    
    def add_user(self, username, password, role, dialog):
        if not username or not password:
            QMessageBox.warning(self, '错误', '请输入用户名和密码')
            return
        
        try:
            headers = {'Authorization': self.token, 'Content-Type': 'application/json'}
            data = {
                'username': username,
                'password': password,
                'role': role
            }
            response = requests.post('http://localhost:5000/admin/users', headers=headers, json=data)
            
            if response.status_code == 201:
                QMessageBox.information(self, '成功', '用户添加成功')
                self.load_users()
                dialog.close()
            else:
                QMessageBox.warning(self, '错误', response.json().get('message', '添加用户失败'))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'添加用户失败: {str(e)}')
    
    def delete_user(self, user_id):
        try:
            headers = {'Authorization': self.token}
            response = requests.delete(f'http://localhost:5000/admin/users/{user_id}', headers=headers)
            
            if response.status_code == 200:
                QMessageBox.information(self, '成功', '用户删除成功')
                self.load_users()
            else:
                QMessageBox.warning(self, '错误', response.json().get('message', '删除用户失败'))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'删除用户失败: {str(e)}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    login_window = LoginWindow()
    if login_window.exec_() == QDialog.Accepted:
        main_window = MainWindow(login_window.token, login_window.current_user)
        main_window.show()
        sys.exit(app.exec_())