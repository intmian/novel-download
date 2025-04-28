import os
import json
import requests
from bs4 import BeautifulSoup
from typing import List
from mods.public import Novel, Chapter, ModInterface
import re

class Lwxsw8Mod(ModInterface):
    base_url = "https://m.lwxsw8.com"

    def search_novels(self, keyword: str) -> List[Novel]:
        url = self.base_url + "/search/"
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
            results.append(Novel(name, author, desc, self.base_url + link + "all.html"))
        return results

    def get_chapters(self, novel_link: str) -> List[Chapter]:
        html_content = self.get_html(novel_link)
        soup = BeautifulSoup(html_content, 'html.parser')
        chapters = []

        for a_tag in soup.select('div.book_last dd a'):
            href = a_tag.get('href')
            title = a_tag.get_text(strip=True)
            if title == "↓↓↓ 直达页面底部":
                continue
            if href and title != "":
                chapter = Chapter(title=title, link=href)
                chapters.append(chapter)
        
        return chapters

    def download_chapter(self, chapter_link: str) -> str:
        html_content = self.get_html(self.base_url + chapter_link)
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

    def assemble_novel(self, chapters: List[Chapter]) -> str:
        novel_text = ""
        for chapter in chapters:
            if chapter.text.strip():
                novel_text += chapter.text + "\n\n------------\n\n"
        return novel_text

    def get_html(self, url: str) -> str:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.text
        else:
            raise Exception(f"Failed to fetch the page: {response.status_code}")

