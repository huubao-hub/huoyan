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
    QGraphicsEllipseItem, QComboBox, QFrame, QGroupBox, QTabWidget
)
from PyQt5.QtGui import (
    QImage, QPixmap, QFont, QPalette, QColor, QIcon, QPainter,
    QLinearGradient, QBrush, QFontDatabase, QPen
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QUrl, QSize, QTimer
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
        self.setWindowTitle('重理工四太子高空瞭望 AI识别管理系统')
        self.setWindowIcon(QIcon('icon.png'))
        self.setFixedSize(600, 450)

        # 设置背景
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a2a6c, stop:1 #b21f1f
                );
                color: white;
                font-family: 'Microsoft YaHei';
            }
            QLabel {
                color: white;
                font-size: 16px;
            }
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 5px;
                padding: 8px;
                color: white;
                font-size: 14px;
                min-width: 250px;
            }
            QPushButton {
                background-color: #4a90e2;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 25px;
                font-size: 16px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #5a9ef2;
            }
            QPushButton:pressed {
                background-color: #3a80d2;
            }
        """)

        # 主布局
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(30)
        layout.setContentsMargins(50, 50, 50, 50)

        # 标题
        title = QLabel("重理工四太子高空瞭望\nAI识别管理系统")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")

        # 输入框容器
        input_container = QVBoxLayout()
        input_container.setSpacing(15)

        # 用户名输入
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText('请输入您的用户名')

        # 密码输入
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText('请输入您的密码')
        self.password_input.setEchoMode(QLineEdit.Password)

        # 登录按钮
        self.login_button = QPushButton('登录')
        self.login_button.clicked.connect(self.handle_login)

        # 添加到布局
        input_container.addWidget(QLabel(""))
        input_container.addWidget(self.username_input)
        input_container.addWidget(self.password_input)
        input_container.addWidget(QLabel(""))
        input_container.addWidget(self.login_button, 0, Qt.AlignCenter)

        # 主布局添加组件
        layout.addWidget(title)
        layout.addLayout(input_container)

        self.setLayout(layout)

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
        self.frame_count = 0
        self.process_every_n_frames = 5  # 每5帧处理一次

    def run(self):
        cap = cv2.VideoCapture(self.stream_url)
        while self.running:
            ret, frame = cap.read()
            if not ret:
                continue
                
            self.frame_count += 1
            if self.frame_count % self.process_every_n_frames != 0:
                continue
                
            # 缩小图像尺寸减轻处理负担
            frame = cv2.resize(frame, (320, 180))

            # 进行火灾检测
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            lower_red = np.array([0, 120, 70])
            upper_red = np.array([10, 255, 255])
            mask = cv2.inRange(hsv, lower_red, upper_red)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if contours:
                c = max(contours, key=cv2.contourArea)
                if cv2.contourArea(c) > 500:  # 面积阈值
                    x, y, w, h = cv2.boundingRect(c)
                    self.frame_received.emit(frame, y, x, x + w, y + h)
                    continue

            self.frame_received.emit(frame, -1, -1, -1, -1)

        cap.release()


class MapViewer(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # 加载地图背景
        self.map_pixmap = QPixmap("map.png")  # 确保有地图图片
        if self.map_pixmap.isNull():
            # 如果没有地图图片，创建一个空白背景
            self.map_pixmap = QPixmap(800, 600)
            self.map_pixmap.fill(QColor(240, 240, 240))

        self.scene.addPixmap(self.map_pixmap)
        self.setRenderHint(QPainter.Antialiasing)

        # 存储报警标记
        self.alarm_markers = {}

    def add_alarm_marker(self, x, y, alarm_id):
        # 创建报警标记（红色圆点）
        marker = self.scene.addEllipse(
            x - 5, y - 5, 10, 10,
            QPen(Qt.red),
            QColor(255, 0, 0, 180)
        )
        self.alarm_markers[alarm_id] = marker

    def remove_alarm_marker(self, alarm_id):
        if alarm_id in self.alarm_markers:
            self.scene.removeItem(self.alarm_markers[alarm_id])
            del self.alarm_markers[alarm_id]

    def clear_markers(self):
        for marker in self.alarm_markers.values():
            self.scene.removeItem(marker)
        self.alarm_markers.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)


class MainWindow(QWidget):
    def __init__(self, token, current_user):
        super().__init__()
        self.token = token
        self.current_user = current_user
        self.alarm_playing = False
        self.init_ui()

        self.video_thread = VideoStreamThread('http://192.168.187.85:8080', self.token)
        self.video_thread.frame_received.connect(self.update_frame)
        self.video_thread.start()

        self.load_alarms_to_map()
        self.update_emergency_stats()
        self.update_alarm_stats()  # 新增：更新预警统计信息

    def init_ui(self):
        self.setWindowTitle('视频AI智能识别及预警管理系统平台')
        self.setWindowIcon(QIcon('icon.png'))
        self.setMinimumSize(1280, 720)

        # 加载字体
        font_id = QFontDatabase.addApplicationFont("fonts/SourceHanSansCN-Medium.ttf")
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            self.setFont(QFont(font_family))

        # 设置主窗口样式
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f2f5;
                color: #333333;
                font-family: 'Microsoft YaHei';
            }

            /* 标题样式 */
            QLabel#Title {
                font-size: 20px;
                font-weight: bold;
                color: #1a2a6c;
                padding: 10px 0;
            }

            /* 信息标签样式 */
            QLabel#Info {
                font-size: 16px;
                padding: 8px;
                background-color: #ffffff;
                border-radius: 5px;
                border: 1px solid #e0e0e0;
            }

            /* 按钮基础样式 */
            QPushButton {
                background-color: #4a90e2;
                color: #ffffff;
                font-size: 14px;
                border-radius: 5px;
                padding: 8px 16px;
                border: none;
                min-width: 80px;
            }

            /* 按钮悬停效果 */
            QPushButton:hover {
                background-color: #5a9ef2;
            }

            /* 按钮按下效果 */
            QPushButton:pressed {
                background-color: #3a80d2;
            }

            /* 特殊按钮样式 */
            QPushButton#AlarmButton {
                background-color: #ff4d4d;
                font-weight: bold;
            }

            QPushButton#AdminButton {
                background-color: #1a2a6c;
            }

            /* 表格样式 */
            QTableWidget {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                gridline-color: #e0e0e0;
                selection-background-color: #e6f2ff;
                selection-color: #333333;
                font-size: 14px;
            }

            QHeaderView::section {
                background-color: #f5f5f5;
                color: #333333;
                padding: 8px;
                border: none;
                font-weight: bold;
            }

            /* 输入框样式 */
            QLineEdit {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 6px;
                font-size: 14px;
            }

            /* 组合框样式 */
            QComboBox {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 6px;
                min-width: 120px;
            }

            /* 分组框样式 */
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                color: #1a2a6c;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }

            /* 分隔线样式 */
            QFrame#Divider {
                background-color: #e0e0e0;
                min-width: 1px;
                max-width: 1px;
            }
        """)

        # 主布局
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # 左侧面板 - 地图和报警列表
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)

        # 顶部标题和日期
        top_bar = QHBoxLayout()

        title_label = QLabel('视频AI智能识别及预警管理系统平台')
        title_label.setObjectName('Title')

        date_label = QLabel(datetime.datetime.now().strftime('%Y-%m-%d %A'))
        date_label.setStyleSheet("font-size: 16px; color: #666666;")

        time_label = QLabel(datetime.datetime.now().strftime('%H:%M:%S'))
        time_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #1a2a6c;")

        top_bar.addWidget(title_label)
        top_bar.addStretch()
        top_bar.addWidget(date_label)
        top_bar.addWidget(time_label)

        # 地图视图
        map_group = QGroupBox("火灾报警地图")
        map_layout = QVBoxLayout()

        self.map_viewer = MapViewer()
        self.map_viewer.setMinimumSize(600, 400)

        map_layout.addWidget(self.map_viewer)
        map_group.setLayout(map_layout)

        # 查询条件
        query_group = QGroupBox("条件查询")
        query_layout = QHBoxLayout()

        start_time_input = QLineEdit()
        start_time_input.setPlaceholderText("起始时间")

        end_time_input = QLineEdit()
        end_time_input.setPlaceholderText("结束时间")

        query_button = QPushButton("查询")

        query_layout.addWidget(start_time_input)
        query_layout.addWidget(end_time_input)
        query_layout.addWidget(query_button)
        query_group.setLayout(query_layout)

        # 报警表格
        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(5)
        self.alarm_table.setHorizontalHeaderLabels(['序号', '地址', '时间', '状态', '操作'])
        self.alarm_table.horizontalHeader().setStretchLastSection(True)
        self.alarm_table.verticalHeader().setVisible(False)
        self.alarm_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.alarm_table.setEditTriggers(QTableWidget.NoEditTriggers)

        left_panel.addLayout(top_bar)
        left_panel.addWidget(map_group)
        left_panel.addWidget(query_group)
        left_panel.addWidget(self.alarm_table)

        # 右侧面板 - 统计信息和视频监控
        right_panel = QVBoxLayout()
        right_panel.setSpacing(15)

        # 预警统计
        stats_group = QGroupBox("预警统计")
        stats_layout = QVBoxLayout()

        stats_grid = QHBoxLayout()

        self.today_label = QLabel("今日\n0")
        self.today_label.setAlignment(Qt.AlignCenter)
        self.today_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                padding: 10px;
                background-color: #f0f7ff;
                border-radius: 5px;
            }
        """)

        self.week_label = QLabel("本周\n0")
        self.week_label.setAlignment(Qt.AlignCenter)
        self.week_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                padding: 10px;
                background-color: #f0f7ff;
                border-radius: 5px;
            }
        """)

        self.month_label = QLabel("本月\n4")
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                padding: 10px;
                background-color: #f0f7ff;
                border-radius: 5px;
            }
        """)

        self.year_label = QLabel("本年\n4")
        self.year_label.setAlignment(Qt.AlignCenter)
        self.year_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                padding: 10px;
                background-color: #f0f7ff;
                border-radius: 5px;
            }
        """)

        stats_grid.addWidget(self.today_label)
        stats_grid.addWidget(self.week_label)
        stats_grid.addWidget(self.month_label)
        stats_grid.addWidget(self.year_label)

        stats_layout.addLayout(stats_grid)
        stats_group.setLayout(stats_layout)

        # 污染排行榜
        pollute_group = QGroupBox("今日污染数据排行榜")
        pollute_layout = QVBoxLayout()

        pollute_list = QLabel("\n".join([
            "1. 重理工校园",
        ]))
        pollute_list.setStyleSheet("font-size: 14px; padding: 10px;")

        pollute_layout.addWidget(pollute_list)
        pollute_group.setLayout(pollute_layout)

        # 紧急程度
        emergency_group = QGroupBox("紧急程度")
        emergency_layout = QVBoxLayout()

        self.emergency_table = QTableWidget()
        self.emergency_table.setColumnCount(3)
        self.emergency_table.setHorizontalHeaderLabels(['区域', '事件数目', '已处理数量'])
        self.emergency_table.setRowCount(1)
        self.emergency_table.setItem(0, 0, QTableWidgetItem("重理工校园"))
        self.emergency_table.setItem(0, 1, QTableWidgetItem("0"))
        self.emergency_table.setItem(0, 2, QTableWidgetItem("0"))
        self.emergency_table.horizontalHeader().setStretchLastSection(True)
        self.emergency_table.verticalHeader().setVisible(False)

        emergency_layout.addWidget(self.emergency_table)
        emergency_group.setLayout(emergency_layout)

        # 视频监控
        video_group = QGroupBox("实时监控画面")
        video_layout = QVBoxLayout()

        self.cv_label = QLabel()
        self.cv_label.setAlignment(Qt.AlignCenter)
        self.cv_label.setStyleSheet("background-color: #000000;")
        self.cv_label.setMinimumSize(640, 360)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(640, 360)
        self.video_widget.hide()

        self.info_label = QLabel()
        self.info_label.setObjectName('Info')
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)

        video_layout.addWidget(self.cv_label)
        video_layout.addWidget(self.video_widget)
        video_layout.addWidget(self.info_label)
        video_group.setLayout(video_layout)

        # 控制按钮
        button_layout = QHBoxLayout()

        self.alarm_button = QPushButton('停止警报')
        self.alarm_button.setObjectName('AlarmButton')
        self.alarm_button.clicked.connect(self.stop_alarm)

        if self.current_user['role'] == 'admin':
            self.admin_button = QPushButton('管理面板')
            self.admin_button.setObjectName('AdminButton')
            self.admin_button.clicked.connect(self.show_admin_panel)
            button_layout.addWidget(self.admin_button)

        button_layout.addStretch()
        button_layout.addWidget(self.alarm_button)

        # 平台信息
        platform_label = QLabel("重理工智慧城市平台\n大气网格化监测及空气质量预警系统\n市环保大气管理平台\n重理工生态视频监控平台")
        platform_label.setAlignment(Qt.AlignCenter)
        platform_label.setStyleSheet("font-size: 12px; color: #666666; padding: 10px;")

        right_panel.addWidget(stats_group)
        right_panel.addWidget(pollute_group)
        right_panel.addWidget(emergency_group)
        right_panel.addWidget(video_group)
        right_panel.addLayout(button_layout)
        right_panel.addWidget(platform_label)

        # 组合主布局
        main_layout.addLayout(left_panel, 60)
        main_layout.addLayout(right_panel, 40)

        self.setLayout(main_layout)

        # 更新时间
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)

    def update_time(self):
        time_label = self.findChild(QLabel)
        if time_label:
            time_label.setText(datetime.datetime.now().strftime('%H:%M:%S'))

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
                image_path = response.json()['video_path']  # 注意: 虽然API路径是video，但实际返回的是图片路径
                if not os.path.exists(image_path):
                    QMessageBox.warning(self, '警告', '图片文件不存在')
                    return

                # 显示图片而不是播放视频
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    QMessageBox.warning(self, '警告', '无法加载图片')
                    return
                    
                # 创建图片查看对话框
                dialog = QDialog(self)
                dialog.setWindowTitle('报警详情')
                layout = QVBoxLayout()
                
                image_label = QLabel()
                image_label.setPixmap(pixmap.scaled(800, 600, Qt.KeepAspectRatio))
                
                close_btn = QPushButton('关闭')
                close_btn.clicked.connect(dialog.close)
                
                layout.addWidget(image_label)
                layout.addWidget(close_btn)
                dialog.setLayout(layout)
                dialog.exec_()
            else:
                QMessageBox.warning(self, '警告', '无法加载报警详情')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'加载报警详情失败: {str(e)}')

    def show_admin_panel(self):
        if self.current_user['role'] == 'admin':
            self.admin_panel = AdminPanel(self.token, self.current_user)
            self.admin_panel.show()

    def update_frame(self, frame, top, left, right, bottom):
        if top != -1 and left != -1 and right != -1 and bottom != -1:
            self.info_label.setText(f"发生火灾! 具体位置： top: {top}, left: {left}, right: {right}, bottom: {bottom}")
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)

            # 保存报警图片
            img_name = f"alarm_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            img_path = os.path.join("alarm_images", img_name)
            
            # 确保目录存在
            os.makedirs("alarm_images", exist_ok=True)
            
            # 保存图片
            cv2.imwrite(img_path, frame)

            try:
                headers = {'Authorization': self.token, 'Content-Type': 'application/json'}
                data = {
                    'top': top,
                    'left': left,
                    'right': right,
                    'bottom': bottom,
                    'image_path': img_path
                }
                response = requests.post('http://localhost:5000/alarms', headers=headers, json=data)

                if response.status_code == 201:
                    self.load_alarms_to_map()
                    self.update_emergency_stats()
            except Exception as e:
                print(f"Failed to save alarm: {str(e)}")

        # 显示处理后的帧
        frame = cv2.resize(frame, (640, 360))  # 调整显示尺寸
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

    def update_emergency_stats(self):
        try:
            headers = {'Authorization': self.token}
            response = requests.get('http://localhost:5000/alarms', headers=headers)

            if response.status_code == 200:
                alarms = response.json()
                total_events = len(alarms)
                processed_events = sum(1 for alarm in alarms if alarm['user_id'] != 0)

                self.emergency_table.setItem(0, 1, QTableWidgetItem(str(total_events)))
                self.emergency_table.setItem(0, 2, QTableWidgetItem(str(processed_events)))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'更新紧急程度统计失败: {str(e)}')

    def update_alarm_stats(self):
        try:
            headers = {'Authorization': self.token}
            response = requests.get('http://localhost:5000/alarms/stats', headers=headers)

            if response.status_code == 200:
                stats = response.json()
                self.today_label.setText(f"今日\n{stats['today']}")
                self.week_label.setText(f"本周\n{stats['week']}")
                self.month_label.setText(f"本月\n{stats['month']}")
                self.year_label.setText(f"本年\n{stats['year']}")
        except Exception as e:
            QMessageBox.critical(self, '错误', f'更新预警统计信息失败: {str(e)}')


class AdminPanel(QWidget):
    def __init__(self, token, current_user):
        super().__init__()
        self.token = token
        self.current_user = current_user
        self.setWindowTitle('管理员面板')
        self.setFixedSize(1000, 800)

        self.tab_widget = QTabWidget()

        # 用户管理标签页
        self.user_tab = QWidget()
        self.init_user_tab()

        # 报警处理标签页
        self.alarm_tab = QWidget()
        self.init_alarm_tab()

        self.tab_widget.addTab(self.user_tab, "用户管理")
        self.tab_widget.addTab(self.alarm_tab, "报警处理")

        layout = QVBoxLayout()
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

        self.load_unprocessed_alarms()

    def init_user_tab(self):
        layout = QVBoxLayout()

        self.user_table = QTableWidget()
        self.user_table.setColumnCount(4)
        self.user_table.setHorizontalHeaderLabels(['ID', '用户名', '角色', '操作'])
        self.load_users()

        self.add_user_btn = QPushButton('添加用户')
        self.add_user_btn.clicked.connect(self.show_add_user_dialog)

        layout.addWidget(self.user_table)
        layout.addWidget(self.add_user_btn)
        self.user_tab.setLayout(layout)

    def init_alarm_tab(self):
        layout = QVBoxLayout()

        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(6)
        self.alarm_table.setHorizontalHeaderLabels(['ID', '时间', '位置', '图片路径', '状态', '操作'])  # 修改表头
        self.alarm_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.alarm_table)
        self.alarm_tab.setLayout(layout)

    def load_unprocessed_alarms(self):
        try:
            headers = {'Authorization': self.token}
            response = requests.get('http://localhost:5000/alarms/unprocessed', headers=headers)

            if response.status_code == 200:
                alarms = response.json()
                self.alarm_table.setRowCount(len(alarms))

                for i, alarm in enumerate(alarms):
                    self.alarm_table.setItem(i, 0, QTableWidgetItem(str(alarm['id'])))
                    self.alarm_table.setItem(i, 1, QTableWidgetItem(alarm['time']))
                    self.alarm_table.setItem(i, 2, QTableWidgetItem(
                        f"Top: {alarm['top_location']}, Left: {alarm['left_location']}"
                    ))
                    # 兼容新旧字段名
                    self.alarm_table.setItem(i, 3, QTableWidgetItem(alarm.get('image_path', alarm.get('video_path', 'N/A'))))
                    self.alarm_table.setItem(i, 4, QTableWidgetItem("未处理"))

                    process_btn = QPushButton('处理')
                    process_btn.clicked.connect(lambda _, id=alarm['id']: self.process_alarm(id))
                    self.alarm_table.setCellWidget(i, 5, process_btn)
        except Exception as e:
            QMessageBox.critical(self, '错误', f'加载未处理报警失败: {str(e)}')

    def process_alarm(self, alarm_id):
        try:
            headers = {'Authorization': self.token}
            response = requests.put(
                f'http://localhost:5000/alarms/{alarm_id}/process',
                headers=headers
            )

            if response.status_code == 200:
                QMessageBox.information(self, '成功', '报警处理成功')
                self.load_unprocessed_alarms()
                main_window = self.parent()
                if main_window:
                    main_window.update_emergency_stats()
            else:
                QMessageBox.warning(self, '错误', response.json().get('message', '处理报警失败'))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'处理报警失败: {str(e)}')

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