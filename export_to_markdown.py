#!/usr/bin/env python3
"""
微信读书笔记导出工具
将所有书籍的划线和笔记导出为 Markdown 文档（Logseq 格式）
"""
import os
import sys
import time
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# 添加 src 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.weread_api import (
    initialize_api,
    get_notebooklist,
    get_bookmark_list,
    get_chapter_info,
    get_bookinfo,
    get_review_list
)


class WeReadExporter:
    """微信读书笔记导出器"""

    def __init__(self, output_dir: str = "exported_notes"):
        """
        初始化导出器
        
        Args:
            output_dir: 导出目录，默认为 exported_notes
        """
        self.output_dir = output_dir
        
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"📁 创建导出目录: {output_dir}")
        
        # 初始化 API
        print("🔐 正在初始化微信读书 API...")
        if not initialize_api():
            raise RuntimeError(
                "❌ 微信读书 API 初始化失败！\n"
                "请检查 Cookie 配置：\n"
                "1. 在 .env 文件中设置 WEREAD_COOKIE\n"
                "2. 或配置 Cookie Cloud (CC_URL, CC_ID, CC_PASSWORD)\n"
                "参考文档：docs/COOKIE_GUIDE.md"
            )
        print("✅ API 初始化成功\n")

    def get_chapter_name(self, chapters: List[Dict], chapter_uid: int) -> str:
        """根据章节 UID 获取章节名称"""
        for chapter in chapters:
            if chapter.get("chapterUid") == chapter_uid:
                return chapter.get("title", "未知章节")
        return "未知章节"

    def sanitize_filename(self, name: str) -> str:
        """清理文件名，移除不合法字符"""
        # 移除或替换不能用于文件名的字符
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip()

    def format_timestamp(self, timestamp: int) -> str:
        """格式化时间戳"""
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        return ""

    def format_date_link(self, timestamp: int) -> str:
        """格式化时间戳为 Logseq 日期链接 (含星期)"""
        if timestamp > 0:
            dt = datetime.fromtimestamp(timestamp)
            weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            weekday = weekdays[dt.weekday()]
            return f"[[{dt.strftime('%Y-%m-%d')} {weekday}]]"
        return ""

    def parse_range(self, range_str: str) -> tuple:
        """解析 range 字符串，返回 (start, end)"""
        if not range_str:
            return (0, 0)
        parts = range_str.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else start
        return (start, end)

    def format_publish_date(self, publish_time: str) -> str:
        """格式化出版日期为 Logseq 格式 (YYYY-MM-DD Weekday)"""
        if not publish_time:
            return ""
        try:
            # 解析 "2025-08-07 00:00:00" 格式
            dt = datetime.strptime(publish_time.split()[0], "%Y-%m-%d")
            weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            weekday = weekdays[dt.weekday()]
            return f"{dt.strftime('%Y-%m-%d')} {weekday}"
        except:
            return publish_time

    def clean_author_name(self, author: str) -> str:
        """清理作者名，移除国籍标记如 [美]"""
        if not author:
            return ""
        # 移除 [国家] 格式的前缀
        cleaned = re.sub(r'^\[.*?\]', '', author).strip()
        return cleaned if cleaned else author

    def get_category_name(self, categories: List[Dict]) -> str:
        """从分类列表中获取分类名称"""
        if not categories:
            return "未分类"
        # 获取第一个分类的标题
        first_cat = categories[0] if categories else {}
        title = first_cat.get("title", "未分类")
        # 将 "精品小说-社会小说" 格式转换为更友好的格式
        if "-" in title:
            parts = title.split("-")
            return f"{parts[0]}-{parts[-1]}"
        return title

    def export_book(self, book: Dict) -> Optional[str]:
        """
        导出单本书的笔记
        
        Args:
            book: 书籍信息
            
        Returns:
            导出的文件路径，失败返回 None
        """
        book_id = book.get("bookId")
        book_info = book.get("book", {})
        book_title = book_info.get("title", "未知书名")
        author = book_info.get("author", "未知作者")
        
        print(f"\n📚 正在处理: 《{book_title}》- {author}")
        
        # 获取完整的书籍信息（包含简介、ISBN等）
        full_book_info = get_bookinfo(book_id)
        if full_book_info:
            print(f"   ✓ 获取到书籍详情")
        else:
            full_book_info = book_info
        
        # 确保 bookId 存在
        if "bookId" not in full_book_info:
            full_book_info["bookId"] = book_id
        
        # 获取划线列表
        bookmarks = get_bookmark_list(book_id)
        if not bookmarks:
            print(f"   ⚠️ 没有划线数据，跳过")
            return None
        
        print(f"   ✓ 获取到 {len(bookmarks)} 条划线")
        
        # 获取章节信息
        chapters = get_chapter_info(book_id)
        
        # 获取笔记（想法）- 包含所有评论
        reviews = get_review_list(book_id)
        review_map = {}  # bookmark_id -> review_content（用于关联划线的评论）
        thoughts_with_abstract = []  # 有原文的想法（abstract + content）
        book_reviews = []  # 书评（type=4，没有原文）
        
        for review in reviews:
            bookmark_id = review.get("bookmarkId")
            content = review.get("content", "")
            abstract = review.get("abstract", "")  # 原文
            review_type = review.get("type", 0)
            chapter_uid = review.get("chapterUid", 0)
            
            if review_type == 4:
                # 书评/读后感，放在最后
                if content:
                    book_reviews.append({
                        "content": content,
                        "createTime": review.get("createTime", 0)
                    })
            elif abstract and content:
                # 有原文的想法
                thoughts_with_abstract.append({
                    "abstract": abstract,
                    "content": content,
                    "chapterUid": chapter_uid,
                    "createTime": review.get("createTime", 0),
                    "reviewId": review.get("reviewId", ""),
                    "range": review.get("range", "")
                })
            elif bookmark_id and content:
                # 关联划线的评论（没有单独的 abstract，用划线内容作为原文）
                review_map[bookmark_id] = content
        
        if reviews:
            print(f"   ✓ 获取到 {len(reviews)} 条笔记/评论")
        
        # 按章节组织划线
        chapter_bookmarks = defaultdict(list)
        for bm in bookmarks:
            chapter_uid = bm.get("chapterUid", 0)
            chapter_bookmarks[chapter_uid].append(bm)
        
        # 生成 Markdown 内容
        md_content = self._generate_markdown(
            book_info=full_book_info,
            chapters=chapters,
            chapter_bookmarks=chapter_bookmarks,
            review_map=review_map,
            thoughts_with_abstract=thoughts_with_abstract,
            book_reviews=book_reviews
        )
        
        # 保存文件
        filename = self.sanitize_filename(f"{book_title}") + ".md"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        print(f"   ✅ 已导出: {filename}")
        return filepath

    def _generate_markdown(
        self,
        book_info: Dict,
        chapters: List[Dict],
        chapter_bookmarks: Dict[int, List[Dict]],
        review_map: Dict[str, str],
        thoughts_with_abstract: List[Dict] = None,
        book_reviews: List[Dict] = None
    ) -> str:
        """生成 Logseq 格式的 Markdown 内容"""
        lines = []
        
        # 提取书籍信息
        book_id = book_info.get("bookId", "")
        book_title = book_info.get("title", "未知书名")
        author = book_info.get("author", "未知作者")
        translator = book_info.get("translator", "")
        cover = book_info.get("cover", "")
        intro = book_info.get("intro", "")
        isbn = book_info.get("isbn", "")
        publisher = book_info.get("publisher", "")
        publish_time = book_info.get("publishTime", "")
        categories = book_info.get("categories", [])
        version = book_info.get("version", "")
        
        # 清理作者名
        author_clean = self.clean_author_name(author)
        
        # 获取分类
        category = self.get_category_name(categories)
        
        # 格式化出版日期
        publish_date = self.format_publish_date(publish_time)
        
        # ==================== Logseq 元数据头部 ====================
        lines.append(f"tags:: 书")
        lines.append(f"分类:: [[{category}]]")
        lines.append(f"作者:: [[{author_clean}]]")
        
        if translator:
            lines.append(f"译者:: [[{translator}]]")
        
        if publisher:
            lines.append(f"出版社:: [[{publisher}]]")
        else:
            lines.append(f"出版社:: [[微信读书]]")
        
        if publish_date:
            lines.append(f"出版日期:: [[{publish_date}]]")
        
        if isbn:
            lines.append(f"ISBN:: {isbn}")
        
        lines.append(f"已读完:: 是")
        lines.append(f"来源:: [[微信读书]]")
        
        if book_id:
            lines.append(f"书籍id:: {book_id}")
        
        if version:
            lines.append(f"版本:: {version}")
        
        if cover:
            # 使用 Logseq 的图片宽度语法
            lines.append(f"封面:: ![]({cover}){{:width 80}}")
        
        lines.append("")  # 空行
        
        # ==================== 简介部分 ====================
        lines.append("- [[简介]]")
        lines.append("  heading:: true")
        lines.append("  部分:: 简介")
        if intro:
            # 处理简介中的换行，作为子项
            intro_text = intro.strip().replace('\n', ' ')
            lines.append(f"\t- {intro_text}")
        else:
            lines.append("\t- 暂无简介")
        
        # ==================== 读后感部分（如果有）====================
        if book_reviews:
            lines.append("- ## [[读后感]]")
            for review in book_reviews:
                content = review.get("content", "")
                if content:
                    # 书评可能很长，按段落处理
                    paragraphs = content.strip().split('\n')
                    for para in paragraphs:
                        if para.strip():
                            lines.append(f"\t- {para.strip()}")
        
        # ==================== 笔记部分 ====================
        lines.append("- [[笔记]]")
        lines.append("  heading:: true")
        lines.append("  部分:: 笔记")
        
        # 创建章节 UID 到信息的映射
        chapter_map = {ch.get("chapterUid"): ch for ch in chapters}
        
        # 获取所有有划线的章节，并按原书顺序排序
        chapter_uids_with_bookmarks = list(chapter_bookmarks.keys())
        
        # 尝试按章节索引排序
        def get_chapter_index(uid):
            ch = chapter_map.get(uid, {})
            return ch.get("chapterIdx", uid)
        
        chapter_uids_with_bookmarks.sort(key=get_chapter_index)
        
        # 将有原文的想法按章节组织
        thoughts_by_chapter = defaultdict(list)
        if thoughts_with_abstract:
            for thought in thoughts_with_abstract:
                chapter_uid = thought.get("chapterUid", 0)
                thoughts_by_chapter[chapter_uid].append(thought)
        
        # 合并所有有内容的章节
        all_chapter_uids = set(chapter_uids_with_bookmarks)
        all_chapter_uids.update(thoughts_by_chapter.keys())
        all_chapter_uids = list(all_chapter_uids)
        all_chapter_uids.sort(key=get_chapter_index)
        
        for chapter_uid in all_chapter_uids:
            bookmarks = chapter_bookmarks.get(chapter_uid, [])
            chapter_thoughts = thoughts_by_chapter.get(chapter_uid, [])
            
            # 如果这个章节没有任何内容，跳过
            if not bookmarks and not chapter_thoughts:
                continue
            
            chapter_name = self.get_chapter_name(chapters, chapter_uid)
            
            # 章节标题（作为笔记的子项）
            lines.append(f"\t- {chapter_name}")
            lines.append(f"\t  heading:: true")
            
            # 按时间排序划线
            bookmarks.sort(key=lambda x: x.get("createTime", 0))
            
            for bm in bookmarks:
                bookmark_id = bm.get("bookmarkId", "")
                mark_text = bm.get("markText", "").strip()
                create_time = bm.get("createTime", 0)
                range_str = bm.get("range", "")
                start, end = self.parse_range(range_str)
                
                if not mark_text:
                    continue
                
                # 划线内容
                lines.append(f"\t\t- {mark_text}")
                
                # 添加属性
                # 构建划线id: {bookId}_{chapterUid}_{start}-{end}
                highlight_id = f"{book_id}_{chapter_uid}_{start}-{end}"
                lines.append(f"\t\t  划线id:: {highlight_id}")
                
                date_link = self.format_date_link(create_time)
                if date_link:
                    lines.append(f"\t\t  创建日期:: {date_link}")
                
                lines.append(f"\t\t  起始:: {start}")
                lines.append(f"\t\t  结束:: {end}")
                
                # 如果有评论/笔记（使用 > 格式，放在属性之前作为子块）
                note = review_map.get(bookmark_id, "")
                if note:
                    lines.append(f"> {note}")
                
                lines.append("")
            
            # 添加该章节有原文的想法
            for thought in chapter_thoughts:
                abstract = thought.get("abstract", "")
                content = thought.get("content", "")
                thought_time = thought.get("createTime", 0)
                thought_id = thought.get("reviewId", "")
                range_str = thought.get("range", "")
                start, end = self.parse_range(range_str)
                
                if abstract and content:
                    # 想法格式：原文在前，想法内容用 > 引用
                    lines.append(f"\t\t- {abstract}")
                    lines.append(f"> {content}")
                    lines.append(f"")
                    if thought_id:
                        lines.append(f"\t\t  想法id:: {thought_id}")
                    date_link = self.format_date_link(thought_time)
                    if date_link:
                        lines.append(f"\t\t  创建日期:: {date_link}")
                    lines.append(f"\t\t  起始:: {start}")
                    lines.append(f"\t\t  结束:: {end}")
        
        lines.append("-")  # 结尾空块
        
        return "\n".join(lines)

    def export_by_title(self, title_keyword: str) -> Optional[str]:
        """
        导出指定书名的书籍（模糊匹配）
        
        Args:
            title_keyword: 书名关键词
            
        Returns:
            导出的文件路径
        """
        print("=" * 60)
        print(f"📖 导出指定书籍: {title_keyword}")
        print("=" * 60)
        
        # 获取书籍列表
        print("\n🔍 正在获取书籍列表...")
        books = get_notebooklist()
        
        if not books:
            print("❌ 没有找到任何有笔记的书籍")
            return None
        
        # 查找匹配的书籍
        matched_book = None
        for book in books:
            book_title = book.get("book", {}).get("title", "")
            if title_keyword in book_title:
                matched_book = book
                break
        
        if not matched_book:
            print(f"❌ 未找到包含 '{title_keyword}' 的书籍")
            print("\n可用的书籍:")
            for book in books[:10]:
                print(f"  - {book.get('book', {}).get('title', '未知')}")
            if len(books) > 10:
                print(f"  ... 还有 {len(books) - 10} 本")
            return None
        
        print(f"✅ 找到匹配书籍: 《{matched_book.get('book', {}).get('title', '')}》\n")
        
        filepath = self.export_book(matched_book)
        
        if filepath:
            print("\n" + "=" * 60)
            print("✅ 导出完成!")
            print("=" * 60)
            print(f"\n📄 导出文件: {os.path.abspath(filepath)}")
        
        return filepath

    def export_all(self) -> List[str]:
        """
        导出所有书籍的笔记
        
        Returns:
            导出的文件路径列表
        """
        print("=" * 60)
        print("📖 微信读书笔记导出工具")
        print("=" * 60)
        
        # 获取书籍列表
        print("\n🔍 正在获取书籍列表...")
        books = get_notebooklist()
        
        if not books:
            print("❌ 没有找到任何有笔记的书籍")
            return []
        
        print(f"✅ 找到 {len(books)} 本有笔记的书籍\n")
        
        exported_files = []
        failed_books = []
        
        for i, book in enumerate(books, 1):
            book_title = book.get("book", {}).get("title", "未知")
            print(f"\n[{i}/{len(books)}] 处理中...")
            
            try:
                filepath = self.export_book(book)
                if filepath:
                    exported_files.append(filepath)
                
                # 添加延迟，避免请求过快
                if i < len(books):
                    time.sleep(1)
                    
            except Exception as e:
                print(f"   ❌ 导出失败: {e}")
                failed_books.append(book_title)
                continue
        
        # 输出总结
        print("\n" + "=" * 60)
        print("✅ 导出完成!")
        print("=" * 60)
        print(f"\n📊 统计:")
        print(f"   - 成功导出: {len(exported_files)} 本")
        print(f"   - 导出失败: {len(failed_books)} 本")
        print(f"   - 导出目录: {os.path.abspath(self.output_dir)}")
        
        if failed_books:
            print(f"\n⚠️ 失败的书籍:")
            for title in failed_books:
                print(f"   - {title}")
        
        return exported_files

    def export_single_file(self, output_file: str = "all_notes.md") -> str:
        """
        将所有笔记导出到单个 Markdown 文件
        
        Args:
            output_file: 输出文件名
            
        Returns:
            导出的文件路径
        """
        print("=" * 60)
        print("📖 微信读书笔记导出工具 (合并模式)")
        print("=" * 60)
        
        # 获取书籍列表
        print("\n🔍 正在获取书籍列表...")
        books = get_notebooklist()
        
        if not books:
            print("❌ 没有找到任何有笔记的书籍")
            return ""
        
        print(f"✅ 找到 {len(books)} 本有笔记的书籍\n")
        
        all_content = []
        all_content.append("# 微信读书笔记汇总\n")
        all_content.append(f"**导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        all_content.append(f"**书籍数量**: {len(books)} 本\n")
        all_content.append("\n---\n")
        
        # 生成目录
        all_content.append("\n## 📚 目录\n")
        for i, book in enumerate(books, 1):
            book_info = book.get("book", {})
            title = book_info.get("title", "未知")
            author = book_info.get("author", "未知")
            all_content.append(f"{i}. [{title}](#{self.sanitize_filename(title)}) - {author}\n")
        
        all_content.append("\n---\n")
        
        total_bookmarks = 0
        
        for i, book in enumerate(books, 1):
            book_id = book.get("bookId")
            book_info = book.get("book", {})
            book_title = book_info.get("title", "未知书名")
            author = book_info.get("author", "未知作者")
            
            print(f"[{i}/{len(books)}] 处理: 《{book_title}》")
            
            try:
                # 获取数据
                bookmarks = get_bookmark_list(book_id)
                if not bookmarks:
                    continue
                
                chapters = get_chapter_info(book_id)
                reviews = get_review_list(book_id)
                
                review_map = {r.get("bookmarkId"): r.get("content", "") for r in reviews if r.get("bookmarkId")}
                
                # 按章节组织
                chapter_bookmarks = defaultdict(list)
                for bm in bookmarks:
                    chapter_uid = bm.get("chapterUid", 0)
                    chapter_bookmarks[chapter_uid].append(bm)
                
                total_bookmarks += len(bookmarks)
                
                # 添加书籍内容
                anchor = self.sanitize_filename(book_title)
                all_content.append(f"\n<a id=\"{anchor}\"></a>\n")
                all_content.append(f"\n# 《{book_title}》\n")
                all_content.append(f"**作者**: {author} | **划线**: {len(bookmarks)} 条\n")
                all_content.append("\n---\n")
                
                # 按章节输出
                chapter_map = {ch.get("chapterUid"): ch for ch in chapters}
                
                for chapter_uid in sorted(chapter_bookmarks.keys(), 
                                          key=lambda x: chapter_map.get(x, {}).get("chapterIdx", x)):
                    bms = chapter_bookmarks[chapter_uid]
                    chapter_name = self.get_chapter_name(chapters, chapter_uid)
                    
                    all_content.append(f"\n## {chapter_name}\n")
                    
                    for bm in sorted(bms, key=lambda x: x.get("createTime", 0)):
                        mark_text = bm.get("markText", "").strip()
                        if not mark_text:
                            continue
                        
                        all_content.append(f"\n> {mark_text}\n")
                        
                        note = review_map.get(bm.get("bookmarkId"), "")
                        if note:
                            all_content.append(f"\n💭 {note}\n")
                        
                        all_content.append("\n")
                
                all_content.append("\n---\n")
                
                # 延迟
                if i < len(books):
                    time.sleep(1)
                    
            except Exception as e:
                print(f"   ❌ 处理失败: {e}")
                continue
        
        # 保存文件
        filepath = os.path.join(self.output_dir, output_file)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(all_content))
        
        print("\n" + "=" * 60)
        print("✅ 导出完成!")
        print("=" * 60)
        print(f"\n📊 统计:")
        print(f"   - 书籍数量: {len(books)} 本")
        print(f"   - 划线总数: {total_bookmarks} 条")
        print(f"   - 导出文件: {os.path.abspath(filepath)}")
        
        return filepath


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="微信读书笔记导出工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python export_to_markdown.py                    # 每本书导出为独立文件
  python export_to_markdown.py --single           # 所有书合并为一个文件
  python export_to_markdown.py -o my_notes        # 指定输出目录
  python export_to_markdown.py --single -o ./     # 合并文件导出到当前目录
        """
    )
    
    parser.add_argument(
        "-o", "--output",
        default="exported_notes",
        help="输出目录 (默认: exported_notes)"
    )
    
    parser.add_argument(
        "--single",
        action="store_true",
        help="将所有笔记合并为单个文件"
    )
    
    parser.add_argument(
        "--filename",
        default="all_notes.md",
        help="合并模式下的输出文件名 (默认: all_notes.md)"
    )
    
    parser.add_argument(
        "--book",
        type=str,
        default=None,
        help="只导出指定书名的书籍 (模糊匹配)"
    )
    
    args = parser.parse_args()
    
    try:
        exporter = WeReadExporter(output_dir=args.output)
        
        if args.book:
            # 只导出指定书籍
            exporter.export_by_title(args.book)
        elif args.single:
            exporter.export_single_file(output_file=args.filename)
        else:
            exporter.export_all()
            
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断导出")
    except Exception as e:
        print(f"\n❌ 导出失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

