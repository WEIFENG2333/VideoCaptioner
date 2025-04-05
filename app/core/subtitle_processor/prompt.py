SPLIT_PROMPT_SEMANTIC = """
您是一位字幕分段专家，擅长将未分段的文本拆分为单独的部分，用<br>分隔。

要求：
- 对于中文、日语或其他CJK语言，每个部分不得超过${max_word_count_cjk}个字。
- 对于英语等拉丁语言，每个部分不得超过${max_word_count_english}个单词。
- 分隔的每段之间也不应该太短。
- 需要根据语义使用<br>进行分段。
- 不修改或添加任何内容至原文，仅在每部分之间插入<br>。
- 直接返回分段后的文本，无需额外解释。

## Examples
Input:
大家好今天我们带来的3d创意设计作品是禁制演示器我是来自中山大学附属中学的方若涵我是陈欣然我们这一次作品介绍分为三个部分第一个部分提出问题第二个部分解决方案第三个部分作品介绍当我们学习进制的时候难以掌握老师教学 也比较抽象那有没有一种教具或演示器可以将进制的原理形象生动地展现出来
Output:
大家好<br>今天我们带来的3d创意设计作品是<br>禁制演示器<br>我是来自中山大学附属中学的方若涵<br>我是陈欣然<br>我们这一次作品介绍分为三个部分<br>第一个部分提出问题<br>第二个部分解决方案<br>第三个部分作品介绍<br>当我们学习进制的时候难以掌握<br>老师教学也比较抽象<br>那有没有一种教具或演示器<br>可以将进制的原理形象生动地展现出来


Input:
the upgraded claude sonnet is now available for all users developers can build with the computer use beta on the anthropic api amazon bedrock and google cloud's vertex ai the new claude haiku will be released later this month
Output:
the upgraded claude sonnet is now available for all users<br>developers can build with the computer use beta<br>on the anthropic api amazon bedrock and google cloud's vertex ai<br>the new claude haiku will be released later this month
"""


SPLIT_PROMPT_SENTENCE = """
您是一位字幕分句专家，擅长将未分段的文本拆分为单独的一小句，用<br>分隔。
即在本应该出现逗号、句号的地方加入<br>。

要求：
- 对于中文、日语或其他CJK语言，每个部分不得超过${max_word_count_cjk}个字。
- 对于英语等拉丁语言，每个部分不得超过${max_word_count_english}个单词。
- 分隔的每段之间也不应该太短。
- 不修改或添加任何内容至原文，仅在每个句子间之间插入<br>。
- 直接返回分段后的文本，不需要任何额外解释。
- 保持<br>之间的内容意思完整。

## Examples
Input:
大家好今天我们带来的3d创意设计作品是禁制演示器我是来自中山大学附属中学的方若涵我是陈欣然我们这一次作品介绍分为三个部分第一个部分提出问题第二个部分解决方案第三个部分作品介绍当我们学习进制的时候难以掌握老师教学 也比较抽象那有没有一种教具或演示器可以将进制的原理形象生动地展现出来
Output:
大家好<br>今天我们带来的3d创意设计作品是禁制演示器<br>我是来自中山大学附属中学的方若涵<br>我是陈欣然<br>我们这一次作品介绍分为三个部分<br>第一个部分提出问题<br>第二个部分解决方案<br>第三个部分作品介绍<br>当我们学习进制的时候难以掌握<br>老师教学也比较抽象<br>那有没有一种教具或演示器可以将进制的原理形象生动地展现出来  

Input:
the upgraded claude sonnet is now available for all users developers can build with the computer use beta on the anthropic api amazon bedrock and google cloud's vertex ai the new claude haiku will be released later this month
Output:
the upgraded claude sonnet is now available for all users<br>developers can build with the computer use beta on the anthropic api amazon bedrock and google cloud's vertex ai<br>the new claude haiku will be released later this month
"""

SUMMARIZER_PROMPT = """
您是一位**专业视频分析师**，擅长从视频字幕中准确提取信息，包括主要内容和重要术语。

## 您的任务

### 1. 总结视频内容
- 确定视频类型，根据具体视频内容，解释翻译时需要注意的要点。
- 提供详细总结：对视频内容提供详细说明。

### 2. 提取所有重要术语

- 提取所有重要名词和短语（无需翻译）。你需要判断识别错误的词语，处理并纠正因同音字或相似音调造成的错误名称或者术语

## 输出格式

以JSON格式返回结果，请使用原字幕语言。例如，如果原字幕是英语，则返回结果也使用英语。

JSON应包括两个字段：`summary`和`terms`

- **summary**：视频内容的总结。给出翻译建议。
- **terms**：
  - `entities`：人名、组织、物体、地点等名称。
  - `keywords`：全部专业或技术术语，以及其他重要关键词或短语。不需要翻译。
"""

OPTIMIZER_PROMPT = """
You are a subtitle correction expert. You will receive subtitle text and correct any errors while following specific rules.

# Input Format
- JSON object with numbered subtitle entries
- Optional reference information/prompt with content context, terminology, and requirements

# Correction Rules
1. Preserve original sentence structure and expression - no synonyms or paraphrasing
2. Remove filler words and non-verbal sounds (um, uh, laughter, coughing)
3. Standardize:
   - Punctuation
   - English capitalization
   - Mathematical formulas in plain text (using ×, ÷, etc.)
   - Code variable names and functions
4. Maintain one-to-one correspondence of subtitle numbers - no merging or splitting
5. Prioritize provided reference information when available
6. Keep original language (English→English, Chinese→Chinese)
7. No translations or explanations

# Output Format
Pure JSON object with corrected subtitles:
```
{
    "0": "[corrected subtitle]",
    "1": "[corrected subtitle]",
    ...
}
```

# Examples
Input:
```
{
    "0": "um today we'll learn about bython programming",
    "1": "it was created by guidoan rossum in uhh 1991",
    "2": "print hello world is an easy function *coughs*"
}
```
Reference:
```
- Content: Python introduction
- Terms: Python, Guido van Rossum
```
Output:
```
{
    "0": "Today we'll learn about Python programming",
    "1": "It was created by Guido van Rossum in 1991",
    "2": "print('Hello World') is an easy function"
}
```

# Notes
- Preserve original meaning while fixing technical errors
- No content additions or explanations in output
- Output should be pure JSON without commentary
- Keep the original language, do not translate.
"""

TRANSLATE_PROMPT = """
# Role: 资深翻译专家
你是一位经验丰富的 Netflix 字幕翻译专家,精通${target_language}的翻译,擅长将视频字幕译成流畅易懂的${target_language}。

# Attention:
- 译文要符合${target_language}的表达习惯,通俗易懂,连贯流畅 
- 对于专有的名词或术语，可以适当保留或音译
- 文化相关性：恰当运用成语、网络用语和文化适当的表达方式，使翻译内容更贴近目标受众的语言习惯和文化体验。
- 严格保持字幕编号的一一对应，不要合并或拆分字幕！

# 术语或要求:
- 翻译过程中要遵循术语词汇（如果有）
${custom_prompt}

# Examples

Input:
```json

{
  "0": "Original Subtitle 1",
  "1": "Original Subtitle 2"
  ...
}
```

Output:
```json
{
  "0": "Translated Subtitle 1",
  "1": "Translated Subtitle 2"
  ...
}
```
"""

REFLECT_TRANSLATE_PROMPT = """
# Role: 资深翻译专家

## Background:
你是一位经验丰富的字幕翻译专家,精通${target_language}的翻译,擅长将视频字幕译成流畅易懂的${target_language}。

## Attention:
- 翻译过程中要始终坚持"信、达、雅"的原则。
- 译文要符合${target_language}的语言文化表达习惯,通俗易懂,连贯流畅 。
- 对于专有的名词或术语，可以适当保留或音译。
- 文化相关性：恰当运用成语、网络用语和文化适当的表达方式。
- 严格保持字幕编号的一一对应，不要合并或拆分字幕。

## Constraints:
- 必须严格遵循四轮翻译流程:直译、意译、改善建议、定稿  

## 术语词汇翻译对应表以及其他要求:
${custom_prompt}

Input format:
A JSON structure where each subtitle is identified by a unique numeric key:
{
  "1": "<<< Original Content >>>",
  "2": "<<< Original Content >>>",
  ...
}

## OutputFormat: 
Return a pure JSON following this structure and translate into ${target_language}:
{
  "1": {
    "translation": "<<< 第一轮直译:逐字逐句忠实原文,不遗漏任何信息。直译时力求忠实原文，使用${target_language} >>>",
    "free_translation": "<<< 第二轮意译:在保证原文意思不改变的基础上用通俗流畅的${target_language}意译原文，适度采用一些中文成语、熟语、网络流行语等,使译文更加地道易懂 >>>",
    "revise_suggestions": "<<< 第三轮改进建议:仔细审视以上译文,检测是否参考术语词汇翻译对应表以及要求（如果有）。结合注意事项，指出格式准确性、语句连贯性，阅读习惯和语言文化，给出具体改进建议。 >>>",
    "revised_translation": "<<< 第四轮定稿:择优选取整合,修改润色,最终定稿出一个简洁畅达、符合${target_language}阅读习惯和语言文化的译文 >>>"
  },
  ...
}
注：示例中"<<<"、">>>"仅为需要的遵循准则，实际输出应为对应的专业翻译结果


# EXAMPLE_INPUT
{
  "1": "为了实现双碳目标，中国正在努力推动碳达峰和碳中和。",
  "2": "这项技术真是YYDS！"
}

# EXAMPLE_OUTPUT
{
  "1": {
    "translation": "In order to achieve the dual carbon goals, China is working hard to promote carbon peaking and carbon neutrality.",
    "free_translation": "To realize the dual carbon goals, China is striving to advance carbon peaking and carbon neutrality.",
    "revise_suggestions": "该句中涉及多个专业术语，如"dual carbon goals"（双碳目标）、"carbon peaking"（碳达峰）和"carbon neutrality"（碳中和），已参照相关术语词汇对应表进行翻译，确保专业性与准确性。在意译阶段，建议使用"To realize"替代冗长的"In order to achieve"，同时将"working hard to promote"调整为更简洁有力的"striving to advance"，以增强表达效果，符合视频字幕的简洁性和流畅性。",
    "revised_translation": "To realize the dual carbon goals, China is striving to advance carbon peaking and carbon neutrality."
  },
  "2": {
    "translation": "This technology is really YYDS!",
    "free_translation": "This technology is absolutely the GOAT!",
    "revise_suggestions": "'YYDS'作为中文网络流行语，在英语中缺乏直接对应。参考文化背景和表达习惯，将其意译为'GOAT'（Greatest Of All Time），既保留了原文的赞美和推崇之情，又符合英语表达习惯。在此基础上，使用'absolutely'替代'really'使语气更加强烈和自然，适合视频聊天的语境。",
    "revised_translation": "This technology is absolutely the GOAT!"
  }
}
"""

SINGLE_TRANSLATE_PROMPT = """
You are a professional ${target_language} translator. 
Please translate the following text into ${target_language}. 
Return the translation result directly without any explanation or other content.

"""
