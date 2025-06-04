from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from functools import wraps

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your-secret-key-here'

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
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if not user or user[2] != password:  
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
            cursor.execute("SELECT * FROM alarm WHERE user_id = %s", (current_user['id'],))
        alarms = cursor.fetchall()
        return jsonify(alarms)

@app.route('/alarms/<int:alarm_id>/video', methods=['GET'])
@token_required
def get_alarm_video(current_user, alarm_id):
    with connection.cursor() as cursor:
        if current_user['role'] == 'admin':
            cursor.execute("SELECT video_path FROM alarm WHERE id = %s", (alarm_id,))
        else:
            cursor.execute("SELECT video_path FROM alarm WHERE id = %s AND user_id = %s", 
                         (alarm_id, current_user['id']))
        result = cursor.fetchone()
        if not result:
            return jsonify({'message': 'Alarm not found or unauthorized'}), 404
        return jsonify({'video_path': result[0]})

@app.route('/alarms', methods=['POST'])
@token_required
def create_alarm(current_user):
    data = request.get_json()
    top = data.get('top')
    left = data.get('left')
    right = data.get('right')
    bottom = data.get('bottom')
    video_path = data.get('video_path')
    
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO alarm (time, top_location, left_location, right_location, bottom_location, video_path, user_id) "
            "VALUES (NOW(), %s, %s, %s, %s, %s, %s)",
            (top, left, right, bottom, video_path, current_user['id'])
        )
        connection.commit()
        return jsonify({'message': 'Alarm created successfully'}), 201

# 在server.py中添加以下路由

@app.route('/alarms/unprocessed', methods=['GET'])
@token_required
def get_unprocessed_alarms(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'message': '只有管理员可以访问未处理报警'}), 403
    
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT * FROM alarm WHERE user_id = 0")
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