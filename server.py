from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
import jwt
import datetime
from functools import wraps
import os

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# 图片保存目录
UPLOAD_FOLDER = 'server_images'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

connection = pymysql.connect(
    host='localhost',
    user='root',
    password='20040429Hxy@',
    database='firealarm_db'
)


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['user']
        except:
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user, *args, **kwargs)

    return decorated


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password required'}), 400

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()

        if not user:
            return jsonify({'message': 'Invalid credentials'}), 401

        token = jwt.encode({
            'user': {
                'id': user[0],
                'username': user[1],
                'role': user[3]
            },
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'])

        return jsonify({
            'token': token,
            'user': {
                'id': user[0],
                'username': user[1],
                'role': user[3]
            }
        })


@app.route('/alarms', methods=['GET'])
@token_required
def get_alarms(current_user):
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        if current_user['role'] == 'admin':
            cursor.execute("SELECT * FROM alarm")
        else:
            # 普通用户只能查看自己的报警记录
            cursor.execute("SELECT * FROM alarm WHERE user_id = %s", (current_user['id'],))
        alarms = cursor.fetchall()
        return jsonify(alarms)


@app.route('/alarms/<int:alarm_id>/video', methods=['GET'])
@token_required
def get_alarm_video(current_user, alarm_id):
    with connection.cursor() as cursor:
        if current_user['role'] == 'admin':
            cursor.execute("SELECT image_path FROM alarm WHERE id = %s", (alarm_id,))
        else:
            cursor.execute("SELECT image_path FROM alarm WHERE id = %s AND user_id = %s",
                           (alarm_id, current_user['id']))
        result = cursor.fetchone()
        if not result:
            return jsonify({'message': 'Alarm not found or unauthorized'}), 404
        return jsonify({'image_path': result[0]})


# 修改create_alarm接口，改为存储图片路径
@app.route('/alarms', methods=['POST'])
@token_required
def create_alarm(current_user):
    top = request.form.get('top')
    left = request.form.get('left')
    right = request.form.get('right')
    bottom = request.form.get('bottom')

    if 'image' not in request.files:
        return jsonify({'message': 'No image part'}), 400
    image = request.files['image']
    if image.filename == '':
        return jsonify({'message': 'No selected image'}), 400
    if image:
        # 生成唯一的文件名
        import uuid
        filename = str(uuid.uuid4()) + '.jpg'
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image.save(image_path)

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO alarm (time, top_location, left_location, right_location, bottom_location, image_path, user_id) "
            "VALUES (NOW(), %s, %s, %s, %s, %s, %s)",
            (top, left, right, bottom, image_path, 0)  # 默认user_id为0表示未处理的报警
        )
        connection.commit()
        return jsonify({'message': 'Alarm created successfully'}), 201


# 用于获取所有用户信息
@app.route('/admin/users', methods=['GET'])
@token_required
def get_all_users(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'message': '只有管理员可以访问用户信息'}), 403

    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        return jsonify(users)


# 用于创建新用户
@app.route('/admin/users', methods=['POST'])
@token_required
def create_user(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'message': '只有管理员可以创建用户'}), 403

    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role')

    if not username or not password or not role:
        return jsonify({'message': '用户名、密码和角色是必需的'}), 400

    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (username, password, role))
        connection.commit()
        return jsonify({'message': '用户创建成功'}), 201


# 新增条件查询接口
@app.route('/alarms/query', methods=['GET'])
@token_required
def query_alarms(current_user):
    """支持时间范围和状态的条件查询"""
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    status = request.args.get('status', type=int)  # 0=未处理，1=已处理

    # 构建查询条件
    base_query = "SELECT * FROM alarm WHERE "
    conditions = []
    params = []

    if start_time and end_time:
        conditions.append("time BETWEEN %s AND %s")
        params.extend([start_time, end_time])

    if status is not None:
        if status == 0:
            conditions.append("user_id = 0")
        else:
            conditions.append("user_id != 0")

    # 组合查询语句
    if not conditions:
        return jsonify([]), 400
    query = base_query + " AND ".join(conditions)

    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        # 管理员可查询所有数据，普通用户仅限自己处理的报警
        if current_user['role'] != 'admin':
            if status == 0:
                return jsonify([]), 403  # 普通用户不可查未处理报警
            query += " AND user_id = %s"
            params.append(current_user['id'])

        cursor.execute(query, params)
        alarms = cursor.fetchall()
        return jsonify(alarms)


# 在server.py中添加以下路由
@app.route('/alarms/unprocessed', methods=['GET'])
@token_required
def get_unprocessed_alarms(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'message': '只有管理员可以访问未处理报警'}), 403

    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT id, time, top_location, left_location, image_path FROM alarm WHERE user_id = 0")
        alarms = cursor.fetchall()
        return jsonify(alarms)


@app.route('/alarms/<int:alarm_id>/process', methods=['PUT'])
@token_required
def process_alarm(current_user, alarm_id):
    if current_user['role'] != 'admin':
        return jsonify({'message': '只有管理员可以处理报警'}), 403

    with connection.cursor() as cursor:
        # 检查报警是否存在且未被处理
        cursor.execute("SELECT id FROM alarm WHERE id = %s AND user_id = 0", (alarm_id,))
        if not cursor.fetchone():
            return jsonify({'message': '报警不存在或已被处理'}), 404

        # 更新处理人ID
        cursor.execute(
            "UPDATE alarm SET user_id = %s WHERE id = %s",
            (current_user['id'], alarm_id)
        )
        connection.commit()
        return jsonify({'message': '报警处理成功'})


@app.route('/alarms/stats', methods=['GET'])
@token_required
def get_alarm_stats(current_user):
    today = datetime.datetime.now().date()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    start_of_month = datetime.datetime(today.year, today.month, 1).date()
    start_of_year = datetime.datetime(today.year, 1, 1).date()

    with connection.cursor() as cursor:
        # 今日报警数量
        cursor.execute("SELECT COUNT(*) FROM alarm WHERE DATE(time) = %s", (today,))
        today_count = cursor.fetchone()[0]

        # 本周报警数量
        cursor.execute("SELECT COUNT(*) FROM alarm WHERE DATE(time) >= %s AND DATE(time) <= %s", (start_of_week, today))
        week_count = cursor.fetchone()[0]

        # 本月报警数量
        cursor.execute("SELECT COUNT(*) FROM alarm WHERE DATE(time) >= %s AND DATE(time) <= %s", (start_of_month, today))
        month_count = cursor.fetchone()[0]

        # 本年报警数量
        cursor.execute("SELECT COUNT(*) FROM alarm WHERE DATE(time) >= %s AND DATE(time) <= %s", (start_of_year, today))
        year_count = cursor.fetchone()[0]

    return jsonify({
        'today': today_count,
        'week': week_count,
        'month': month_count,
        'year': year_count
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)