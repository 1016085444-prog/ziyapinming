/* 极简、安全的 Markdown 渲染：先把整段文字做 HTML 转义，再只生成我们自己的标签。
 * 大模型的输出、新闻标题都是不可信内容，绝不能原样当 HTML 插入页面。
 * 支持：标题、粗体/斜体/删除线、行内代码、代码块、有序/无序列表（含缩进嵌套）、表格、引用、分隔线、http(s) 链接。
 */
(function () {
  'use strict';

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // 行内格式：输入已转义
  function inline(s) {
    var codes = [];
    s = s.replace(/`([^`]+)`/g, function (_, c) { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function (_, text, url) {
      return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + text + '</a>';
    });
    s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_]+?)__/g, '<strong>$1</strong>');
    s = s.replace(/~~([^~]+?)~~/g, '<del>$1</del>');
    s = s.replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?!\w)/g, '$1<em>$2</em>');
    s = s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return '<code>' + codes[+i] + '</code>'; });
    return s;
  }

  function splitRow(line) {
    var t = line.trim();
    if (t.charAt(0) === '|') t = t.slice(1);
    if (t.charAt(t.length - 1) === '|') t = t.slice(0, -1);
    return t.split('|').map(function (c) { return c.trim(); });
  }

  function isTableSep(line) {
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
  }

  function render(src) {
    var lines = esc(String(src || '').replace(/\r\n?/g, '\n')).split('\n');
    var out = [];
    var para = [];
    var listStack = []; // [{type, indent}]

    function flushPara() {
      if (para.length) { out.push('<p>' + para.map(inline).join('<br>') + '</p>'); para = []; }
    }
    function closeLists(toIndent) {
      while (listStack.length && (toIndent === undefined || listStack[listStack.length - 1].indent > toIndent)) {
        out.push('</li></' + listStack.pop().type + '>');
      }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var m;

      // 代码块
      if (/^\s*```/.test(line)) {
        flushPara(); closeLists();
        var code = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
        out.push('<pre><code>' + code.join('\n') + '</code></pre>');
        continue;
      }
      if (!line.trim()) { flushPara(); if (!(lines[i + 1] || '').match(/^\s*([-*+]|\d+[.)])\s+/)) closeLists(); continue; }

      // 表格：本行有 |，下一行是分隔行
      if (line.indexOf('|') >= 0 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        flushPara(); closeLists();
        var head = splitRow(line);
        var aligns = splitRow(lines[i + 1]).map(function (c) {
          return /^:-+:$/.test(c) ? 'center' : /-+:$/.test(c) ? 'right' : '';
        });
        var html = '<div class="tbl-x"><table><thead><tr>' + head.map(function (c, k) {
          return '<th' + (aligns[k] ? ' style="text-align:' + aligns[k] + '"' : '') + '>' + inline(c) + '</th>';
        }).join('') + '</tr></thead><tbody>';
        for (i += 2; i < lines.length && lines[i].indexOf('|') >= 0 && lines[i].trim(); i++) {
          html += '<tr>' + splitRow(lines[i]).map(function (c, k) {
            return '<td' + (aligns[k] ? ' style="text-align:' + aligns[k] + '"' : '') + '>' + inline(c) + '</td>';
          }).join('') + '</tr>';
        }
        i--;
        out.push(html + '</tbody></table></div>');
        continue;
      }

      if ((m = line.match(/^\s*(#{1,6})\s+(.*)$/))) {
        flushPara(); closeLists();
        var level = Math.min(6, m[1].length + 2);
        out.push('<h' + level + '>' + inline(m[2].replace(/\s*#+\s*$/, '')) + '</h' + level + '>');
        continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushPara(); closeLists(); out.push('<hr>'); continue; }
      if ((m = line.match(/^\s*&gt;\s?(.*)$/))) {
        flushPara(); closeLists();
        var quote = [m[1]];
        while (i + 1 < lines.length && (m = lines[i + 1].match(/^\s*&gt;\s?(.*)$/))) { quote.push(m[1]); i++; }
        out.push('<blockquote>' + quote.map(inline).join('<br>') + '</blockquote>');
        continue;
      }
      if ((m = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/))) {
        flushPara();
        var indent = m[1].replace(/\t/g, '    ').length;
        var type = /\d/.test(m[2]) ? 'ol' : 'ul';
        var top = listStack[listStack.length - 1];
        if (!top || indent > top.indent) {
          out.push('<' + type + '><li>');
          listStack.push({ type: type, indent: indent });
        } else {
          closeLists(indent);
          top = listStack[listStack.length - 1];
          if (top && top.type !== type && top.indent === indent) {
            out.push('</li></' + listStack.pop().type + '><' + type + '><li>');
            listStack.push({ type: type, indent: indent });
          } else if (top) {
            out.push('</li><li>');
          } else {
            out.push('<' + type + '><li>');
            listStack.push({ type: type, indent: indent });
          }
        }
        out.push(inline(m[3]));
        continue;
      }
      if (listStack.length && /^\s{2,}\S/.test(line)) { out.push('<br>' + inline(line.trim())); continue; }
      closeLists();
      para.push(line.trim());
    }
    flushPara(); closeLists();
    return out.join('');
  }

  // 去掉决策类智能体末尾给程序读的 JSON 块（界面上单独用卡片展示）
  function stripJson(text) {
    return String(text || '').replace(/```(?:json)?\s*\{[\s\S]*?\}\s*```/g, '').replace(/```(?:json)?\s*\{[\s\S]*$/, '').trim();
  }

  window.MD = { render: render, escape: esc, stripJson: stripJson };
})();
