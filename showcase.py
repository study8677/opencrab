import os
import subprocess
import datetime
import sys


class Showcase:
    """生成和检查仓库状态卡，实现自刷新闸功能。"""

    def __init__(self, repo_path='.', output_dir='docs', max_age_hours=24):
        self.repo_path = repo_path
        self.output_dir = output_dir
        self.output_file = os.path.join(output_dir, 'index.html')
        self.max_age_hours = max_age_hours

    def get_repo_stats(self):
        """从真实仓库获取统计信息。"""
        stats = {}
        # 获取提交数
        try:
            result = subprocess.run(['git', 'log', '--oneline'], cwd=self.repo_path, capture_output=True, text=True)
            if result.returncode == 0:
                commits = result.stdout.strip().split('\n')
                stats['commit_count'] = len(commits)
                stats['last_commit'] = commits[0] if commits else 'None'
            else:
                stats['commit_count'] = 0
                stats['last_commit'] = 'Error'
        except Exception as e:
            stats['commit_count'] = 0
            stats['last_commit'] = f'Exception: {e}'

        # 获取分支数
        try:
            result = subprocess.run(['git', 'branch', '-a'], cwd=self.repo_path, capture_output=True, text=True)
            if result.returncode == 0:
                branches = [b.strip() for b in result.stdout.split('\n') if b.strip()]
                stats['branch_count'] = len(branches)
            else:
                stats['branch_count'] = 0
        except:
            stats['branch_count'] = 0

        # 获取模块数
        try:
            py_files = [f for f in os.listdir(self.repo_path) 
                       if f.endswith('.py') and not f.startswith('test_')]
            stats['module_count'] = len(py_files)
        except Exception:
            stats['module_count'] = 0

        # 生成时间
        stats['generated_at'] = datetime.datetime.now().isoformat()
        stats['max_age_hours'] = self.max_age_hours
        return stats

    def generate_status_card(self, stats):
        """生成HTML状态卡并写入文件。"""
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>仓库状态卡</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .card {{ border: 1px solid #ccc; padding: 20px; border-radius: 5px; }}
        .stat {{ margin-bottom: 10px; }}
        .label {{ font-weight: bold; }}
        .value {{ color: #333; }}
        .freshness {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>仓库状态卡</h1>
        <div class="stat">
            <span class="label">模块数量：</span>
            <span class="value">{stats.get('module_count', 'N/A')}</span>
        </div>
        <div class="stat">
            <span class="label">提交数量：</span>
            <span class="value">{stats.get('commit_count', 'N/A')}</span>
        </div>
        <div class="stat">
            <span class="label">分支数量：</span>
            <span class="value">{stats.get('branch_count', 'N/A')}</span>
        </div>
        <div class="stat">
            <span class="label">最后提交：</span>
            <span class="value">{stats.get('last_commit', 'N/A')}</span>
        </div>
        <div class="stat">
            <span class="label">生成时间：</span>
            <span class="value">{stats.get('generated_at', 'N/A')}</span>
        </div>
        <div class="freshness">
            此状态卡在生成时自动刷新。过期时间：{self.max_age_hours}小时。
        </div>
    </div>
</body>
</html>"""

        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def check_freshness(self, max_age_hours=None):
        """检查状态卡是否过期。返回True表示过期。"""
        if max_age_hours is None:
            max_age_hours = self.max_age_hours
            
        if not os.path.exists(self.output_file):
            return True

        file_mtime = os.path.getmtime(self.output_file)
        file_time = datetime.datetime.fromtimestamp(file_mtime)
        now = datetime.datetime.now()
        age = now - file_time
        return age > datetime.timedelta(hours=max_age_hours)

    def refresh_if_needed(self, max_age_hours=None):
        """检查并刷新状态卡，提供过期提醒。"""
        if max_age_hours is None:
            max_age_hours = self.max_age_hours
            
        if self.check_freshness(max_age_hours):
            print("状态卡已过期或不存在，正在刷新...")
            stats = self.get_repo_stats()
            self.generate_status_card(stats)
            print("状态卡已更新。")
            return True
        else:
            print("状态卡仍然新鲜，无需刷新。")
            return False


def auto_refresh():
    """模块导入时自动刷新机制"""
    max_hours = int(os.environ.get('SHOWCASE_MAX_AGE_HOURS', '24'))
    repo_path = os.environ.get('SHOWCASE_REPO_PATH', '.')
    output_dir = os.environ.get('SHOWCASE_OUTPUT_DIR', 'docs')
    
    showcase = Showcase(repo_path, output_dir, max_hours)
    return showcase.refresh_if_needed()

# 当模块被导入时，如果环境变量设置了自动刷新，则执行
if os.environ.get('SHOWCASE_AUTO_REFRESH', '').lower() in ('1', 'true', 'yes'):
    auto_refresh()

if __name__ == '__main__':
    showcase = Showcase()
    showcase.refresh_if_needed()
