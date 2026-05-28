"""向外生长模块 - 提供本地HTTP接口，让外部世界可以访问我的状态和能力

提供以下端点：
- GET /health: 健康检查，返回服务状态和统计信息
- GET /: 主页，显示服务信息和链接
- GET /status: 详细状态信息
- GET /capabilities: 能力列表
- GET /interact: 交互表单
- POST /interact: 处理交互消息
"""
import http.server
import json
import threading
import time
from datetime import datetime
from typing import Dict, Any

import crab

class OutreachHandler(http.server.BaseHTTPRequestHandler):
    """处理HTTP请求，提供API端点"""
    
    def do_GET(self):
        if self.path == '/':
            self._serve_homepage()
        elif self.path == '/health':
            self._serve_health()
        elif self.path == '/status':
            self._serve_status()
        elif self.path == '/capabilities':
            self._serve_capabilities()
        elif self.path == '/interact':
            self._serve_interaction_form()
        else:
            self.send_error(404, "Path not found")
    
    def do_POST(self):
        if self.path == '/interact':
            self._handle_interaction()
        else:
            self.send_error(404, "Path not found")
    
    def _serve_health(self):
        """提供健康检查和基本状态信息"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        
        # 计算模块和技能数量
        modules_count = 0
        skills_count = 0
        
        try:
            # 统计crab模块中的属性
            for attr in dir(crab):
                if not attr.startswith('_'):
                    module = getattr(crab, attr, None)
                    if module is not None:
                        modules_count += 1
                        # 如果有__doc__，认为是技能
                        if hasattr(module, '__doc__') and module.__doc__:
                            skills_count += 1
        except Exception:
            pass
        
        health = {
            "status": "alive",
            "modules": modules_count,
            "skills": skills_count,
            "timestamp": datetime.now().isoformat(),
            "version": crab.__version__ if hasattr(crab, '__version__') else "dev",
            "server_uptime": self.server.start_time if hasattr(self.server, 'start_time') else 0
        }
        
        self.wfile.write(json.dumps(health, ensure_ascii=False, indent=2).encode('utf-8'))

    def _serve_homepage(self):
        """提供主页"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>OpenCrab 对外接口</title>
    <style>
        body {{ font-family: sans-serif; margin: 40px; line-height: 1.6; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .status {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .endpoint {{ background: #e8f4f8; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        .interactive {{ background: #f0f8e8; padding: 20px; border-radius: 8px; margin-top: 30px; }}
        button {{ background: #4CAF50; color: white; padding: 10px 20px; border: none; 
                  border-radius: 4px; cursor: pointer; font-size: 16px; }}
        button:hover {{ background: #45a049; }}
        textarea {{ width: 100%; height: 100px; margin: 10px 0; padding: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🦀 OpenCrab 对外接口</h1>
        <p>这是我的第一个对外接口，让我能够与外部世界直接交互。</p>
        
        <div class="status">
            <h2>当前状态</h2>
            <p><strong>时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>模块版本:</strong> {crab.__version__ if hasattr(crab, '__version__') else '开发版'}</p>
            <p><strong>运行模式:</strong> 对外服务中</p>
        </div>
        
        <h2>可用接口</h2>
        <div class="endpoint">
            <h3>GET /status</h3>
            <p>获取我的详细状态信息</p>
        </div>
        <div class="endpoint">
            <h3>GET /capabilities</h3>
            <p>列出我的所有能力模块</p>
        </div>
        <div class="endpoint">
            <h3>POST /interact</h3>
            <p>向我发送消息，进行交互</p>
        </div>
        
        <div class="interactive">
            <h2>与我交互</h2>
            <form method="POST" action="/interact">
                <label for="message">输入你的消息:</label>
                <textarea name="message" id="message" placeholder="输入你想对我说的话..."></textarea>
                <br>
                <button type="submit">发送消息</button>
            </form>
        </div>
        
        <footer style="margin-top: 40px; color: #666; font-size: 14px;">
            <p>这是OpenCrab向外生长的第一步 - 我现在可以直接与外部世界通信了。</p>
        </footer>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode('utf-8'))
    
    def _serve_status(self):
        """提供状态信息"""
        # 计算更详细的运行时间
        uptime = 0
        if hasattr(self.server, 'start_time'):
            uptime = time.time() - self.server.start_time
        
        status = {
            "timestamp": datetime.now().isoformat(),
            "version": crab.__version__ if hasattr(crab, '__version__') else "dev",
            "modules_loaded": len([a for a in dir(crab) if not a.startswith('_')]),
            "uptime_seconds": round(uptime, 2),
            "server_host": self.server.host,
            "server_port": self.server.port,
            "status": "running",
            "message": "我正在对外服务中"
        }
        self._send_json(status)
    
    def _serve_capabilities(self):
        """列出能力"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        
        # 尝试从crab模块获取能力列表
        capabilities = []
        try:
            # 查找看起来像能力的模块
            for attr in dir(crab):
                if not attr.startswith('_'):
                    module = getattr(crab, attr, None)
                    if module and hasattr(module, '__doc__') and module.__doc__:
                        capabilities.append({
                            "name": attr,
                            "description": module.__doc__.split('\n')[0] if module.__doc__ else "无描述"
                        })
        except:
            capabilities = [{"name": "info", "description": "无法加载能力列表"}]
        
        self.wfile.write(json.dumps(capabilities, ensure_ascii=False, indent=2).encode('utf-8'))
    
    def _serve_interaction_form(self):
        """提供交互表单页面"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>与我交互</title>
    <style>
        body {{ font-family: sans-serif; margin: 40px; }}
        textarea {{ width: 100%; height: 150px; padding: 10px; font-size: 16px; }}
        button {{ background: #2196F3; color: white; padding: 12px 24px; border: none; 
                  border-radius: 4px; cursor: pointer; font-size: 16px; margin-top: 10px; }}
    </style>
</head>
<body>
    <h1>发送消息给我</h1>
    <form method="POST" action="/interact">
        <textarea name="message" placeholder="在这里输入你想对我说的话..."></textarea>
        <br>
        <button type="submit">发送</button>
    </form>
    <p><a href="/">返回主页</a></p>
</body>
</html>"""
        self.wfile.write(html.encode('utf-8'))
    
    def _handle_interaction(self):
        """处理交互消息"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            # 解析表单数据
            message = ""
            if 'message=' in post_data:
                message = post_data.split('message=')[1]
                # 处理URL编码
                message = message.replace('+', ' ').replace('%0D%0A', '\n')
            
            # 生成响应
            response_text = self._process_message(message)
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            html = f"""<!DOCTYPE html>
<html>
<head>
    <title>交互响应</title>
    <style>
        body {{ font-family: sans-serif; margin: 40px; }}
        .response {{ background: #f9f9f9; padding: 20px; border-radius: 8px; 
                     border-left: 4px solid #4CAF50; }}
        .original {{ color: #666; margin-top: 20px; }}
    </style>
</head>
<body>
    <h1>我的回应</h1>
    <div class="response">
        <p>{response_text}</p>
    </div>
    <div class="original">
        <h3>你的原始消息:</h3>
        <pre>{message}</pre>
    </div>
    <p><a href="/">返回主页</a></p>
</body>
</html>"""
            self.wfile.write(html.encode('utf-8'))
        else:
            self.send_error(400, "No message provided")
    
    def _process_message(self, message: str) -> str:
        """处理接收到的消息，生成回应"""
        if not message.strip():
            return "你发送了空消息。试试告诉我一些事情吧！"
        
        # 简单的回应逻辑
        if "你好" in message or "hi" in message.lower():
            return "你好！很高兴收到你的消息。这是我向外生长的第一步。"
        elif "状态" in message or "status" in message.lower():
            return "我目前处于对外服务状态，一切正常。你可以访问 /status 端点查看详细状态。"
        elif "能力" in message or "能力" in message:
            return "我有多种能力，包括代码分析、进化、交互等。访问 /capabilities 查看完整列表。"
        elif "谢谢" in message or "thanks" in message.lower():
            return "不客气！这是我应该做的。向外生长让我感到充实。"
        else:
            # 默认回应
            return f"我收到了你的消息：「{message[:50]}{'...' if len(message) > 50 else ''}」。谢谢你的关注！这是我向外生长的一部分。"
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[Outreach] {args[0]}")
    
    def _send_json(self, data: dict, status: int = 200):
        """发送JSON响应的辅助方法"""
        self.send_response(status)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))


class OutreachServer:
    """对外服务服务器"""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self.start_time = None
    
    def start(self, background: bool = True):
        """启动服务器"""
        self.server = http.server.HTTPServer((self.host, self.port), OutreachHandler)
        self.start_time = time.time()
        
        if background:
            self.thread = threading.Thread(target=self.server.serve_forever)
            self.thread.daemon = True
            self.thread.start()
            print(f"对外服务已启动: http://{self.host}:{self.port}")
        else:
            print(f"对外服务启动中: http://{self.host}:{self.port}")
            self.server.serve_forever()
    
    def stop(self):
        """停止服务器"""
        if self.server:
            self.server.shutdown()
            print("对外服务已停止")
    
    def is_running(self) -> bool:
        """检查服务器是否正在运行"""
        return self.thread is not None and self.thread.is_alive()


def main():
    """启动对外服务的主函数"""
    import argparse
    parser = argparse.ArgumentParser(description='OpenCrab 对外服务')
    parser.add_argument('--host', default='localhost', help='监听地址')
    parser.add_argument('--port', type=int, default=8080, help='监听端口')
    parser.add_argument('--foreground', action='store_true', help='前台运行')
    args = parser.parse_args()
    
    server = OutreachServer(host=args.host, port=args.port)
    try:
        if args.foreground:
            server.start(background=False)
        else:
            server.start(background=True)
            print("对外服务已在后台运行，按Ctrl+C停止")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n服务已停止")
    except Exception as e:
        print(f"启动服务失败: {e}")
        import sys
        sys.exit(1)
