from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List
import os
import json
import re
from tqdm import tqdm
import requests
import shutil
import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QListWidget, QTextEdit, QMessageBox, QFileDialog, QProgressBar, QInputDialog, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QMovie
import importlib.util

baseUrl = "https://m.lwxsw8.com"
NOVEL_LIST_FILE = os.path.join(os.getcwd(), "novel_list.json")
BOOK_DATA_DIR = os.path.join(os.getcwd(), "book_data")
BOOKS_DIR = os.path.join(os.getcwd(), "books")
MODS_DIR = os.path.join(os.getcwd(), "mods")
MODS_PUBLIC_FILE = os.path.join(MODS_DIR, "public.py")
CONFIG_FILE = os.path.join(os.getcwd(), "config.json")

@dataclass
class Chapter:
    title: str
    link: str
    text: str
    content_get: str = None

def ensure_dirs():
    os.makedirs(BOOK_DATA_DIR, exist_ok=True)
    os.makedirs(BOOKS_DIR, exist_ok=True)
    os.makedirs(MODS_DIR, exist_ok=True)

def extract_chapters(html_content: str) -> List[Chapter]:
    soup = BeautifulSoup(html_content, 'html.parser')
    chapters = []

    for a_tag in soup.select('div.book_last dd a'):
        href = a_tag.get('href')
        title = a_tag.get_text(strip=True)
        if title == "↓↓↓ 直达页面底部":
            continue
        if href and title != "":
            chapter = Chapter(title=title, link=href, text="")
            chapters.append(chapter)
    
    return chapters

def get_html(url: str) -> str:
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        return response.text
    else:
        raise Exception(f"Failed to fetch the page: {response.status_code}")

def extract_chapter_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    content_div = soup.find('div', {'id': 'chaptercontent'})
    if not content_div:
        return ""
    for script in content_div.find_all('script'):
        script.decompose()
    lines = []
    for elem in content_div.contents:
        if elem.name == 'br':
            lines.append('\n')
        elif hasattr(elem, 'get_text'):
            lines.append(elem.get_text(strip=True))
        elif isinstance(elem, str):
            lines.append(elem.strip())
    text = ''.join(lines)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'记住手机版网址：.*', '', text)
    return text.strip()

def save_state(state_file, state):
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=4)

def merge_chapters(chapters, output_file):
    with open(output_file, "w", encoding="utf-8") as f:
        for chapter in chapters:
            if chapter.text.strip():
                f.write(chapter.text + "\n\n------------\n\n")
            else:
                print(f"章节 {chapter.title} 没有内容，跳过。")

def load_novel_list():
    if os.path.exists(NOVEL_LIST_FILE):
        with open(NOVEL_LIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 兼容老数据
            if isinstance(data, dict) and "novels" not in data:
                # 老格式，升级
                novels = {}
                for k, v in data.items():
                    novels[k] = v
                    novels[k]["mod"] = None
                return {"novels": novels, "last_mod": None}
            return data
    return {"novels": {}, "last_mod": None}

def save_novel_list(novel_list):
    with open(NOVEL_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(novel_list, f, ensure_ascii=False, indent=4)

def search_novel(keyword):
    url = baseUrl + "/search/"
    data = {
        "searchkey": keyword,
        "searchtype": "all",
        "t_btnsearch": ""
    }
    resp = requests.post(url, data=data, timeout=10)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for table in soup.find_all("table", class_="list-item"):
        a_title = table.find("div", class_="article").find("a", href=True)
        if not a_title:
            continue
        name = a_title.get_text(strip=True)
        link = a_title["href"]
        if not link.endswith("/"):
            continue
        author = ""
        p = table.find("p", class_="fs12 gray")
        if p:
            author = p.get_text(strip=True)
            author = re.sub(r"阅读:\d+", "", author).strip()
            author = re.sub(r"作者:", "", author).strip()
        desc_a = table.find_all("a", href=True)
        desc = ""
        if len(desc_a) > 1:
            desc = desc_a[-1].get_text(strip=True)
        results.append({
            "name": name,
            "url": baseUrl + link + "all.html",
            "author": author,
            "desc": desc
        })
    return results

def export_all_books(novel_list):
    print("正在导出所有小说到 books 文件夹...")
    for title, info in novel_list.items():
        author = info.get("author", "")
        base_folder = os.path.join(BOOK_DATA_DIR, title)
        output_folder = os.path.join(base_folder, "output")
        src_file = os.path.join(output_folder, f"{title}.txt")
        if os.path.exists(src_file):
            author_str = f"({author})" if author else ""
            dst_file = os.path.join(BOOKS_DIR, f"{title}{author_str}.txt")
            shutil.copyfile(src_file, dst_file)
            print(f"已导出: {dst_file}")
        else:
            print(f"未找到小说 {title} 的成品文件，跳过。")
    print("全部导出完成。\n")

class DownloadThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, str, int, int, int, list)
    
    def __init__(self, title, url, author, mod):
        super().__init__()
        self.title = title
        self.url = url
        self.author = author
        self.mod = mod
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        title, novel_url, author, mod = self.title, self.url, self.author, self.mod
        base_folder = os.path.join(BOOK_DATA_DIR, title)
        output_folder = os.path.join(base_folder, "output")
        chapter_folder = os.path.join(base_folder, "chapter")
        state_file = os.path.join(base_folder, "state.json")
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(chapter_folder, exist_ok=True)
        if os.path.exists(state_file):
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {"downloaded": []}
        html_content = mod.get_html(novel_url)
        chapters = mod.get_chapters(novel_url)
        downloaded_set = set(state["downloaded"])
        for chapter in chapters:
            safe_name = chapter.link.lstrip('/').replace('/', '_') + ".txt"
            chapter_path = os.path.join(chapter_folder, safe_name)
            if os.path.exists(chapter_path):
                downloaded_set.add(chapter.link)
                with open(chapter_path, "r", encoding="utf-8") as cf:
                    chapter.text = cf.read()
            else:
                chapter_path_old = os.path.join(chapter_folder, chapter.title + ".txt")
                if os.path.exists(chapter_path_old):
                    downloaded_set.add(chapter.link)
                    with open(chapter_path_old, "r", encoding="utf-8") as cf:
                        chapter.text = cf.read()
            if chapter.text == "":
                downloaded_set.discard(chapter.link)
        state["downloaded"] = list(downloaded_set)
        to_download = [chapter for chapter in chapters if chapter.link not in state["downloaded"]]
        success, fail, consecutive_fail = 0, 0, 0
        progress_msgs = []
        for idx, chapter in enumerate(to_download):
            if self._stopped:
                progress_msgs.append("用户已手动停止下载。")
                break
            try:
                chapter.text = mod.download_chapter(chapter.link)
                if chapter.text.strip():
                    safe_name = chapter.link.lstrip('/').replace('/', '_') + ".txt"
                    chapter_path = os.path.join(chapter_folder, safe_name)
                    with open(chapter_path, "w", encoding="utf-8") as cf:
                        cf.write(chapter.text)
                    state["downloaded"].append(chapter.link)
                    success += 1
                    consecutive_fail = 0
                    msg = f"[{chapter.title}] ({idx+1}/{len(to_download)}) 已下载"
                else:
                    fail += 1
                    consecutive_fail += 1
                    msg = f"[{chapter.title}] ({idx+1}/{len(to_download)}) 下载失败"
            except Exception as e:
                fail += 1
                consecutive_fail += 1
                msg = f"[{chapter.title}] ({idx+1}/{len(to_download)}) 下载异常: {e}"
            progress_msgs.append(msg)
            self.progress.emit(idx + 1, len(to_download), msg)
            if consecutive_fail >= 2:
                break
        unDownload = 0
        for chapter in chapters:
            if chapter.text == "" and chapter.link not in state["downloaded"]:
                unDownload += 1
        downloaded_set = set(state["downloaded"])
        state["downloaded"] = list(downloaded_set)
        save_state(state_file, state)
        output_file = os.path.join(output_folder, f"{title}.txt")
        novel_text = mod.assemble_novel(chapters)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(novel_text)
        author_str = f"({author})" if author else ""
        books_output_file = os.path.join(BOOKS_DIR, f"{title}{author_str}.txt")
        shutil.copyfile(output_file, books_output_file)
        self.finished.emit(output_file, books_output_file, success, fail, unDownload, progress_msgs)

class SearchThread(QThread):
    result = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, keyword, mod):
        super().__init__()
        self.keyword = keyword
        self.mod = mod

    def run(self):
        try:
            results = self.mod.search_novels(self.keyword)
            self.result.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class LoadChaptersThread(QThread):
    result = pyqtSignal(int, int, str)
    error = pyqtSignal(str)

    def __init__(self, name, url, mod):
        super().__init__()
        self.name = name
        self.url = url
        self.mod = mod

    def run(self):
        try:
            base_folder = os.path.join(BOOK_DATA_DIR, self.name)
            chapter_folder = os.path.join(base_folder, "chapter")
            state_file = os.path.join(base_folder, "state.json")
            html_content = self.mod.get_html(self.url)
            chapters = self.mod.get_chapters(self.url)
            total_chapters = len(chapters)
            downloaded_set = set()
            if os.path.exists(state_file):
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    downloaded_set = set(state.get("downloaded", []))
            else:
                if os.path.exists(chapter_folder):
                    downloaded_set = set([
                        fname[:-4] for fname in os.listdir(chapter_folder) if fname.endswith(".txt")
                    ])
            downloaded_count = len(downloaded_set)
            self.result.emit(downloaded_count, total_chapters, "")
        except Exception as e:
            self.error.emit(str(e))

class NovelDownloaderUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("小说下载器")
        self.resize(800, 600)
        self.novel_list_data = load_novel_list()
        self.novel_list = self.novel_list_data.get("novels", {})
        
        self.current_search_results = []
        self.current_selected_novel = None
        self.current_chapter_count = None
        self.current_downloaded_count = None
        self.loading_movie = None
        self.is_downloading = False
        self.download_start_time = None
        self.last_progress_value = 0
        self.mods = self.load_mods()
        self.current_mod = None
        ensure_dirs()
        self.last_selected_mod = self.load_last_selected_mod()
        
        self.init_ui()

    def load_last_selected_mod(self):
        # 优先从 novel_list.json 读取 last_mod
        if self.novel_list_data.get("last_mod"):
            return self.novel_list_data["last_mod"]
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("last_mod", None)
            except Exception:
                return None
        return None

    def save_last_selected_mod(self, mod_name):
        self.novel_list_data["last_mod"] = mod_name
        save_novel_list(self.novel_list_data)
        # 兼容 config.json
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        config["last_mod"] = mod_name
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def init_ui(self):
        layout = QVBoxLayout()
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入小说关键词")
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.on_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self.on_novel_selected)
        layout.addWidget(self.list_widget)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        layout.addWidget(self.info_text)
        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("下载/更新")
        self.download_btn.clicked.connect(self.on_download)
        self.export_btn = QPushButton("导出所有小说")
        self.export_btn.clicked.connect(self.on_export_all)
        self.refresh_btn = QPushButton("显示已保存小说")
        self.refresh_btn.clicked.connect(self.on_refresh_saved)
        self.delete_btn = QPushButton("删除小说")
        self.delete_btn.clicked.connect(self.on_delete_novel)
        self.open_books_btn = QPushButton("打开导出目录")
        self.open_books_btn.clicked.connect(self.on_open_books_dir)
        self.open_mods_btn = QPushButton("打开mods目录")
        self.open_mods_btn.clicked.connect(self.on_open_mods_dir)
        self.mod_selector = QComboBox()
        self.mod_selector.addItems(self.mods.keys())
        if self.last_selected_mod and self.last_selected_mod in self.mods:
            idx = list(self.mods.keys()).index(self.last_selected_mod)
            self.mod_selector.setCurrentIndex(idx)
        self.mod_selector.currentIndexChanged.connect(self.on_mod_selected)
        self.on_mod_selected(self.mod_selector.currentIndex(),first=True)
        btn_layout.addWidget(self.download_btn)
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.open_books_btn)
        btn_layout.addWidget(self.open_mods_btn)
        btn_layout.addWidget(QLabel("选择mod:"))
        btn_layout.addWidget(self.mod_selector)
        layout.addLayout(btn_layout)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_time_label = QLabel("")
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_time_label)
        layout.addLayout(progress_layout)
        # 加载动画和底部提示
        bottom_layout = QHBoxLayout()
        self.loading_label = QLabel()
        self.loading_label.setFixedSize(40, 40)
        self.loading_label.setVisible(False)
        bottom_layout.addWidget(self.loading_label)
        self.tips_label = QLabel(
            "power by intmian@github，放弃除著名权外一切权力，禁止盗版使用，禁止商业使用，禁止结果的任何形式的转载和传播。\n"
        )
        self.tips_label.setWordWrap(True)
        bottom_layout.addWidget(self.tips_label)
        layout.addLayout(bottom_layout)
        self.setLayout(layout)
        self.refresh_saved_list()
        # 备注直接显示在文字栏
        self.info_text.setText(
            "网站高峰期存在访问限制，如果连续下载失败，请稍后再试或者切换网络（VPN）。\n"
            "搜索可能会出现很多奇怪的结果，是引流内容，请忽略。仅供用户进行爬虫学习使用，禁止进行盗版用途使用。"
        )

    def load_mods(self):
        mods = {}
        for mod_name in os.listdir(MODS_DIR):
            mod_path = os.path.join(MODS_DIR, mod_name, "script.py")
            if os.path.exists(mod_path):
                spec = importlib.util.spec_from_file_location(mod_name, mod_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mods[mod_name] = mod.Lwxsw8Mod()
        return mods

    def on_mod_selected(self, index, first = False):
        mod_name = self.mod_selector.currentText()
        self.current_mod = self.mods.get(mod_name)
        self.save_last_selected_mod(mod_name)
        # 切换mod时弹窗提示
        if not first:
            QMessageBox.information(self, "切换mod", "切换mod后只显示该mod保存的小说，下载同名小说会覆盖原有数据。")
        self.refresh_saved_list()

    def show_loading(self, show=True):
        if show:
            if not self.loading_movie:
                gif_path = os.path.join(os.getcwd(), "loading.gif")
                if os.path.exists(gif_path):
                    self.loading_movie = QMovie(gif_path)
                    self.loading_movie.setScaledSize(self.loading_label.size())  # 缩放gif
                    self.loading_label.setMovie(self.loading_movie)
                else:
                    self.loading_label.setText("加载中...")
            if self.loading_movie:
                self.loading_movie.start()
            self.loading_label.setVisible(True)
        else:
            if self.loading_movie:
                self.loading_movie.stop()
            self.loading_label.setVisible(False)

    def refresh_saved_list(self):
        self.list_widget.clear()
        self.novel_list_data = load_novel_list()
        self.novel_list = self.novel_list_data.get("novels", {})
        # 只显示当前mod的小说
        mod_name = self.mod_selector.currentText()
        for k, v in self.novel_list.items():
            if v.get("mod") == mod_name:
                author = v.get("author", "")
                self.list_widget.addItem(f"{k}（{author}）")
        self.current_search_results = []
        self.info_text.clear()
        self.current_selected_novel = None
        self.current_chapter_count = None
        self.current_downloaded_count = None

    def on_refresh_saved(self):
        self.refresh_saved_list()

    def on_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入关键词")
            return
        if not self.current_mod:
            QMessageBox.warning(self, "提示", "请选择一个mod")
            return
        self.list_widget.clear()
        self.info_text.setText("正在搜索...")
        self.search_btn.setEnabled(False)
        self.search_input.setEnabled(False)
        self.show_loading(True)
        QApplication.processEvents()
        # 启动搜索线程
        self.search_thread = SearchThread(keyword, self.current_mod)
        self.search_thread.result.connect(self.on_search_result)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.start()

    def on_search_result(self, results):
        self.show_loading(False)
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.current_search_results = results
        self.list_widget.clear()
        for item in results:
            author = item.author
            desc = item.description
            desc = desc.replace('\n', '').replace('\r', '')
            desc = desc[:30] + "..." if len(desc) > 30 else desc
            self.list_widget.addItem(f"{item.title}（{author}） - {desc}")
        if not results:
            self.info_text.setText("未找到相关小说。")
        else:
            self.info_text.setText("请选择小说进行下载。")
        self.current_selected_novel = None
        self.current_chapter_count = None
        self.current_downloaded_count = None

    def on_search_error(self, msg):
        self.show_loading(False)
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.info_text.setText(f"搜索失败: {msg}")

    def on_novel_selected(self):
        idx = self.list_widget.currentRow()
        if self.current_search_results:
            if 0 <= idx < len(self.current_search_results):
                item = self.current_search_results[idx]
                self.current_selected_novel = item
                info = f"书名: {item.title}\n作者: {item.author}\n简介: {item.description}\n链接: {item.link}"
                self.info_text.setText(info)
                self.current_chapter_count = None
                self.current_downloaded_count = None
        else:
            # 只查找当前mod下的小说
            mod_name = self.mod_selector.currentText()
            keys = [k for k, v in self.novel_list.items() if v.get("mod") == mod_name]
            if 0 <= idx < len(keys):
                name = keys[idx]
                author = self.novel_list[name].get("author", "")
                url = self.novel_list[name]["url"]
                self.current_selected_novel = {"name": name, "author": author, "url": url}
                # 清空文字栏并显示加载提示
                self.info_text.clear()
                self.info_text.setText("正在加载章节...")
                self.show_loading(True)
                QApplication.processEvents()
                # 启动章节加载线程
                self.load_chapters_thread = LoadChaptersThread(name, url, self.current_mod)
                self.load_chapters_thread.result.connect(self.on_load_chapters_result)
                self.load_chapters_thread.error.connect(self.on_load_chapters_error)
                self.load_chapters_thread.start()

    def on_load_chapters_result(self, downloaded_count, total_chapters, _):
        self.show_loading(False)
        name = self.current_selected_novel["name"]
        author = self.current_selected_novel.get("author", "")
        url = self.current_selected_novel["url"]
        self.current_chapter_count = total_chapters
        self.current_downloaded_count = downloaded_count
        self.info_text.setText(
            f"书名: {name}\n作者: {author}\n链接: {url}\n"
            f"已下载章节: {downloaded_count} / {total_chapters}"
        )

    def on_load_chapters_error(self, msg):
        self.show_loading(False)
        self.current_chapter_count = 0
        self.current_downloaded_count = 0
        self.info_text.setText(f"加载章节失败: {msg}")

    def on_download(self):
        if self.is_downloading:
            # 停止下载
            if hasattr(self, 'download_thread') and self.download_thread.isRunning():
                self.download_thread.stop()
            self.info_text.append("正在停止下载...")
            self.download_btn.setEnabled(False)
            return
        if self.current_selected_novel is None:
            QMessageBox.warning(self, "提示", "请先选择小说")
            return
        if not self.current_mod:
            QMessageBox.warning(self, "提示", "请选择一个mod")
            return
        mod_name = self.mod_selector.currentText()
        name = self.current_selected_novel["name"]
        url = self.current_selected_novel["url"]
        author = self.current_selected_novel.get("author", "")
        # 只查找当前mod下的小说
        exist = name in self.novel_list and self.novel_list[name].get("mod") == mod_name
        # 检查是否有同名但不同mod的小说
        if name in self.novel_list and not exist:
            # 如果url不同，弹窗提醒并清理原有数据
            old_url = self.novel_list[name].get("url")
            if old_url != url:
                reply = QMessageBox.question(self, "警告", f"同名小说已存在于其他mod下，下载将覆盖并删除原有数据，是否继续？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return
                # 删除原有数据
                base_folder = os.path.join(BOOK_DATA_DIR, name)
                if os.path.exists(base_folder):
                    shutil.rmtree(base_folder, ignore_errors=True)
                author_str = f"({self.novel_list[name].get('author','')})" if self.novel_list[name].get('author','') else ""
                books_output_file = os.path.join(BOOKS_DIR, f"{name}{author_str}.txt")
                if os.path.exists(books_output_file):
                    os.remove(books_output_file)
                # 删除映射
                del self.novel_list[name]
                self.novel_list_data["novels"] = self.novel_list
                save_novel_list(self.novel_list_data)
        # 新增：如果是新小说，弹出输入框确认名称
        if not exist:
            new_name, ok = QInputDialog.getText(self, "确认小说名称", "请输入小说名称：", QLineEdit.EchoMode.Normal, name)
            if not ok or not new_name.strip():
                QMessageBox.warning(self, "提示", "小说名称不能为空，已取消下载")
                return
            name = new_name.strip()
            self.current_selected_novel["name"] = name
            self.novel_list[name] = {"url": url, "author": author, "mod": mod_name}
            self.novel_list_data["novels"] = self.novel_list
            save_novel_list(self.novel_list_data)
        self.progress_bar.setValue(0)
        self.progress_time_label.setText("")
        self.download_btn.setText("停止")
        self.download_btn.setEnabled(True)
        self.is_downloading = True
        self.info_text.append("开始下载...")
        self.show_loading(True)
        self.download_start_time = None
        self.last_progress_value = 0
        self.download_thread = DownloadThread(name, url, author, self.current_mod)
        self.download_thread.progress.connect(self.on_download_progress)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.start()

    def on_download_progress(self, current, total, msg):
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            # 预估剩余时间
            import time
            now = time.time()
            if self.download_start_time is None or current < self.last_progress_value:
                self.download_start_time = now
                self.last_progress_value = current
            elapsed = now - self.download_start_time if self.download_start_time else 0
            if current > 0 and elapsed > 0:
                speed = elapsed / current
                remain = (total - current) * speed
                if remain > 0:
                    mins, secs = divmod(int(remain), 60)
                    time_str = f"剩余约 {mins}分{secs}秒"
                else:
                    time_str = ""
            else:
                time_str = ""
            self.progress_time_label.setText(time_str)
            self.last_progress_value = current
        else:
            self.progress_bar.setValue(0)
            self.progress_time_label.setText("")
        self.info_text.append(msg)
        self.info_text.moveCursor(self.info_text.textCursor().MoveOperation.End)

    def on_download_finished(self, output_file, books_output_file, success, fail, unDownload, progress_msgs):
        self.download_btn.setEnabled(True)
        self.download_btn.setText("下载/更新")
        self.is_downloading = False
        self.show_loading(False)
        self.progress_time_label.setText("")
        msg = f"下载完成！\n输出文件: {output_file}\n已导出到: {books_output_file}\n成功: {success}，失败: {fail}，未下载: {unDownload}"
        self.info_text.append(msg)
        self.progress_bar.setValue(100)
        # self.refresh_saved_list()
        QMessageBox.information(self, "下载完成", msg)

    def on_export_all(self):
        self.export_btn.setEnabled(False)
        export_all_books(self.novel_list)
        self.export_btn.setEnabled(True)
        QMessageBox.information(self, "导出完成", "全部小说已导出到 books 文件夹。")

    def on_delete_novel(self):
        idx = self.list_widget.currentRow()
        if self.current_search_results:
            QMessageBox.warning(self, "提示", "只能删除已保存的小说")
            return
        # 只查找当前mod下的小说
        mod_name = self.mod_selector.currentText()
        keys = [k for k, v in self.novel_list.items() if v.get("mod") == mod_name]
        if 0 <= idx < len(keys):
            name = keys[idx]
            reply = QMessageBox.question(self, "确认删除", f"确定要删除小说《{name}》及其所有数据吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                base_folder = os.path.join(BOOK_DATA_DIR, name)
                if os.path.exists(base_folder):
                    shutil.rmtree(base_folder, ignore_errors=True)
                author = self.novel_list[name].get("author", "")
                author_str = f"({author})" if author else ""
                books_output_file = os.path.join(BOOKS_DIR, f"{name}{author_str}.txt")
                if os.path.exists(books_output_file):
                    os.remove(books_output_file)
                del self.novel_list[name]
                self.novel_list_data["novels"] = self.novel_list
                save_novel_list(self.novel_list_data)
                self.refresh_saved_list()
                QMessageBox.information(self, "删除成功", f"小说《{name}》已删除。")
        else:
            QMessageBox.warning(self, "提示", "请选择要删除的小说")

    def on_open_books_dir(self):
        path = os.path.abspath(BOOKS_DIR)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def on_open_mods_dir(self):
        path = os.path.abspath(MODS_DIR)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

def main():
    app = QApplication(sys.argv)
    win = NovelDownloaderUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
