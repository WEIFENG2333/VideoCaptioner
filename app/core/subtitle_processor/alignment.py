import difflib


class SubtitleAligner:
    """
    字幕文本对齐器，用于对齐两个文本序列,支持基于相似度的匹配。当目标文本缺少某项时,会使用其上一项进行填充。

    使用示例:
        # 输入文本
        text1 = ['ab', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']  # 源文本
        text2 = ['a',  'b', 'c', 'd', 'f', 'g', 'h', 'i']       # 目标文本

        # 创建对齐器并执行对齐
        text_aligner = SubtitleAligner()
        aligned_source, aligned_target = text_aligner.align_texts(text1, text2)

        # 对齐结果
        aligned_source: ['ab', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']  # 源文本保持不变
        aligned_target: ['a',  'b', 'c', 'd', 'd', 'f', 'g', 'h', 'i']  # 缺失的'e'由'd'填充
    """

    def __init__(self):
        self.line_numbers = [0, 0]

    def align_texts(self, source_text, target_text):
        """
        Align two texts and return the paired lines.

        Args:
            source_text (list): List of lines from the source text.
            target_text (list): List of lines from the target text.

        Returns:
            tuple: Two lists containing aligned lines from source and target texts.
        """
        diff_iterator = difflib.ndiff(source_text, target_text)
        return self._pair_lines(diff_iterator)

    def _pair_lines(self, diff_iterator):
        """
        Pair lines from the diff iterator.

        Args:
            diff_iterator: Iterator from difflib.ndiff()

        Returns:
            tuple: Two lists containing aligned lines from source and target texts.
        """
        source_lines = []
        target_lines = []
        flag = 0

        for source_line, target_line, _ in self._line_iterator(diff_iterator):
            if source_line is not None:
                if source_line[1] == "\n":
                    flag += 1
                    continue
                source_lines.append(source_line[1])
            if target_line is not None:
                if flag > 0:
                    flag -= 1
                    continue
                target_lines.append(target_line[1])

        for i in range(1, len(target_lines)):
            if target_lines[i] == "\n":
                target_lines[i] = target_lines[i - 1]
                # target_lines[i] = source_lines[i]
                # target_lines[i + 1] = source_lines[i + 1]
                # target_lines[i - 1] = source_lines[i - 1]

        return source_lines, target_lines

    def _line_iterator(self, diff_iterator):
        """
        Iterate through diff lines and yield paired lines.

        Args:
            diff_iterator: Iterator from difflib.ndiff()

        Yields:
            tuple: (source_line, target_line, has_diff)
        """
        lines = []
        blank_lines_pending = 0
        blank_lines_to_yield = 0

        while True:
            while len(lines) < 4:
                lines.append(next(diff_iterator, "X"))

            diff_type = "".join([line[0] for line in lines])

            if diff_type.startswith("X"):
                blank_lines_to_yield = blank_lines_pending
            elif diff_type.startswith("-?+?"):
                yield (
                    self._format_line(lines, "?", 0),
                    self._format_line(lines, "?", 1),
                    True,
                )
                continue
            elif diff_type.startswith("--++"):
                blank_lines_pending -= 1
                yield self._format_line(lines, "-", 0), None, True
                continue
            elif diff_type.startswith(("--?+", "--+", "- ")):
                source_line, target_line = self._format_line(lines, "-", 0), None
                blank_lines_to_yield, blank_lines_pending = blank_lines_pending - 1, 0
            elif diff_type.startswith("-+?"):
                yield (
                    self._format_line(lines, None, 0),
                    self._format_line(lines, "?", 1),
                    True,
                )
                continue
            elif diff_type.startswith("-?+"):
                yield (
                    self._format_line(lines, "?", 0),
                    self._format_line(lines, None, 1),
                    True,
                )
                continue
            elif diff_type.startswith("-"):
                blank_lines_pending -= 1
                yield self._format_line(lines, "-", 0), None, True
                continue
            elif diff_type.startswith("+--"):
                blank_lines_pending += 1
                yield None, self._format_line(lines, "+", 1), True
                continue
            elif diff_type.startswith(("+ ", "+-")):
                source_line, target_line = None, self._format_line(lines, "+", 1)
                blank_lines_to_yield, blank_lines_pending = blank_lines_pending + 1, 0
            elif diff_type.startswith("+"):
                blank_lines_pending += 1
                yield None, self._format_line(lines, "+", 1), True
                continue
            elif diff_type.startswith(" "):
                yield (
                    self._format_line(lines[:], None, 0),
                    self._format_line(lines, None, 1),
                    False,
                )
                continue

            while blank_lines_to_yield < 0:
                blank_lines_to_yield += 1
                yield None, ("", "\n"), True
            while blank_lines_to_yield > 0:
                blank_lines_to_yield -= 1
                yield ("", "\n"), None, True

            if diff_type.startswith("X"):
                return
            else:
                yield source_line, target_line, True

    def _format_line(self, lines, format_key, side):
        """
        Format a line with the appropriate markup.

        Args:
            lines (list): List of lines to process.
            format_key (str): Formatting key ('?', '-', '+', or None).
            side (int): 0 for source, 1 for target.

        Returns:
            tuple: (line_number, formatted_text)
        """
        self.line_numbers[side] += 1
        if format_key is None:
            return self.line_numbers[side], lines.pop(0)[2:]
        if format_key == "?":
            text = lines.pop(0)
            lines.pop(0)  # Skip markers line
            text = text[2:]
        else:
            text = lines.pop(0)[2:]
            if not text:
                text = ""
        return self.line_numbers[side], text


if __name__ == "__main__":
    # 简短示例
    text1 = ["ab", "b", "c", "d", "e", "f", "g", "h", "i"]
    text2 = ["a", "b", "c", "d", "f", "g", "h", "i"]

    # 使用示例
    text_aligner = SubtitleAligner()

    aligned_source, aligned_target = text_aligner.align_texts(text1, text2)

    print("Aligned Source:", len(aligned_source))
    print("Aligned Target:", len(aligned_target))
    print(aligned_source)
    print(aligned_target)

    i = 1
    for l1, l2 in zip(aligned_source, aligned_target):
        print(f"行 {i}:")
        print(f"文本1: {l1}")
        print(f"文本2: {l2}")
        print(difflib.SequenceMatcher(None, l1, l2).ratio())
        print("----")
        i += 1

    # d = difflib.HtmlDiff()
    # html = d.make_file(text1, text2)
    # with open('../output/diff.html', 'w', encoding='utf-8') as f:
    #     f.write(html)
