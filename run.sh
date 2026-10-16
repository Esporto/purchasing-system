# 1. Schema
mysql -u root -p < schema.sql

# 2. Python deps
pip install mysqlclient

# 3. Env
export PROC_DB_HOST=127.0.0.1
export PROC_DB_PORT=3306
export PROC_DB_USER=root
export PROC_DB_PASS=your_mysql_root_password
export PROC_DB_NAME=alu_glass_procurement
export PROC_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export PROC_ADMIN_PASSWORD="your_strong_admin_password"

# 4. Run
python backend_server.py