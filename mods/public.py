from typing import List, Dict

class Novel:
    def __init__(self, title: str, author: str, description: str, link: str):
        self.title = title
        self.author = author
        self.description = description
        self.link = link

class Chapter:
    def __init__(self, title: str, link: str, text: str = ""):
        self.title = title
        self.link = link
        self.text = text

class ModInterface:
    def search_novels(self, keyword: str) -> List[Novel]:
        raise NotImplementedError

    def get_chapters(self, novel_link: str) -> List[Chapter]:
        raise NotImplementedError

    def download_chapter(self, chapter_link: str) -> str:
        raise NotImplementedError

    def assemble_novel(self, chapters: List[Chapter]) -> str:
        raise NotImplementedError
