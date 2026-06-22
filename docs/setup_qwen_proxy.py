import paramiko, base64

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('173.249.51.164', port=22, username='root', password='Aa1236987456!')

# Nginx config with proper $ - will be base64 encoded before sending
config = f"""
server {{
    listen 8556;
    server_name _;

    location / {{
        proxy_pass http://10.66.66.7:8555;
        proxy_set_header Host ${{'$'}}host;
        proxy_set_header X-Real-IP ${{'$'}}remote_addr;
        proxy_set_header X-Forwarded-For ${{'$'}}proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${{'$'}}scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }}
}}

server {{
    listen 8002;
    server_name _;

    location / {{
        proxy_pass http://10.66.66.7:8001;
        proxy_set_header Host ${{'$'}}host;
        proxy_set_header X-Real-IP ${{'$'}}remote_addr;
        proxy_set_header X-Forwarded-For ${{'$'}}proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${{'$'}}scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }}
}}
"""

encoded = base64.b64encode(config.encode()).decode()

stdin, stdout, stderr = ssh.exec_command(f'echo {encoded} | base64 -d > /etc/nginx/sites-enabled/qwen-proxy.conf && nginx -t')
stdout_lines = stdout.read().decode('utf-8', errors='replace').strip()
stderr_lines = stderr.read().decode('utf-8', errors='replace').strip()
print('stdout:')
print(stdout_lines)
print('stderr:')
print(stderr_lines)

# Check config
stdin, stdout, stderr = ssh.exec_command('grep proxy_set_header /etc/nginx/sites-enabled/qwen-proxy.conf | head -5')
print('\nHeaders check:')
print(stdout.read().decode('utf-8', errors='replace'))

# Reload if config is valid
if 'successful' in stdout_lines.lower():
    stdin, stdout, stderr = ssh.exec_command('systemctl reload nginx')
    print('\nReload:', stdout.read().decode('utf-8', errors='replace'))
else:
    print('\nConfig invalid, showing raw file:')
    stdin, stdout, stderr = ssh.exec_command('cat /etc/nginx/sites-enabled/qwen-proxy.conf')
    print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
