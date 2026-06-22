import paramiko, base64

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('173.249.51.164', port=22, username='root', password='Aa1236987456!')

# First, create the nginx config content in Python
# The $ signs are literal $ - they should stay as $
nginx_config = """
server {
    listen 8556;
    server_name _;

    location / {
        proxy_pass http://10.66.66.7:8555;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}

server {
    listen 8002;
    server_name _;

    location / {
        proxy_pass http://10.66.66.7:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
"""

# Base64 encode the config in Python (before any shell sees it)
encoded = base64.b64encode(nginx_config.encode()).decode()

# Use /bin/bash directly to decode and write - single quotes prevent expansion
cmd = f"echo {encoded} | base64 -d > /etc/nginx/sites-enabled/qwen-proxy.conf && nginx -t 2>&1"

# Force bash shell by using /bin/bash -c
(stdin, stdout, stderr) = ssh.exec_command(f'/bin/bash -c "{cmd}"')

stdout_str = stdout.read().decode('utf-8', errors='replace')
stderr_str = stderr.read().decode('utf-8', errors='replace')

print(f"stdout: {stdout_str}")
print(f"stderr: {stderr_str}")

# Verify config
(stdin, stdout, stderr) = ssh.exec_command('grep -n "proxy_set_header" /etc/nginx/sites-enabled/qwen-proxy.conf')
print(f"\nConfig lines:")
print(stdout.read().decode('utf-8', errors='replace'))

# Test nginx again
(stdin, stdout, stderr) = ssh.exec_command('nginx -t 2>&1')
print(f"\nFinal nginx -t:")
print(stdout.read().decode('utf-8', errors='replace'))
if 'successful' in stderr.lower() or 'syntax is ok' in ''.join([stdout.read().decode('utf-8', errors='replace')]).lower():
    # Reload
    (stdin2, stdout2, stderr2) = ssh.exec_command('systemctl reload nginx')
    print(f"\nReload: OK")

ssh.close()
