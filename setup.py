# setup.py
from setuptools import setup, find_packages

setup(
    name='ncm-cli',
    version='0.1.0',
    description='NetEase Cloud Music CLI Tool',
    author='Your Name',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    py_modules=['ncm'],
    install_requires=[
        'requests',
        'click',  # 如果使用 cli.py
        # 添加其他依赖
    ],
    entry_points={
        'console_scripts': [
            'ncm = ncm.cli:main',  # 如果有命令行入口
        ],
    },
)