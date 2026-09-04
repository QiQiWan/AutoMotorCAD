/* MotorCAD Studio V0.91.8 — deterministic bilingual UI authority. */
(() => {
  const STORAGE_KEY = 'motorcad-studio-language';
  const SUPPORTED = new Set(['zh', 'en']);
  const SKIP_SELECTOR = 'script,style,noscript,template,code,pre,[data-i18n-skip]';
  const ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'aria-description'];
  const textState = new WeakMap();
  const attrState = new WeakMap();
  let observer = null;
  let flushFrame = 0;
  const pendingNodes = new Set();

  const normalizeLanguage = value => String(value || '').toLowerCase().startsWith('en') ? 'en' : 'zh';
  const language = () => normalizeLanguage(localStorage.getItem(STORAGE_KEY) || document.documentElement.lang || 'zh');
  const hasChinese = value => /[\u3400-\u9fff]/.test(String(value || ''));
  const hasLatinWord = value => /[A-Za-z]{3,}/.test(String(value || ''));

  const zhToEn = new Map();
  const enToZh = new Map();
  const keyCatalog = {...(window.MCS_LOCALES || {})};
  const registerPair = (zh, en) => {
    const left = String(zh ?? '').trim();
    const right = String(en ?? '').trim();
    if (!left || !right) return;
    if (!zhToEn.has(left)) zhToEn.set(left, right);
    if (!enToZh.has(right)) enToZh.set(right, left);
  };
  (window.MCS_LOCALE_PHRASES || []).forEach(row => Array.isArray(row) && registerPair(row[0], row[1]));
  Object.values(keyCatalog).forEach(row => row && registerPair(row.zh, row.en));

  // Common runtime sentences with variable values are translated before phrase substitution.
  const templates = {
    en: [
      [/^(\d+)\s*项待确认$/, '$1 items need review'],
      [/^(\d+)\s*个验证步骤$/, '$1 validation steps'],
      [/^查看\s*(\d+)\s*个标准验证步骤$/, 'View $1 standard validation steps'],
      [/^还需处理\s*(\d+)\s*项$/, '$1 items remaining'],
      [/^(\d+)\s*个阻断项$/, '$1 blocking items'],
      [/^(\d+)\s*个阻断，\s*(\d+)\s*个提示$/, '$1 blocking items, $2 warnings'],
      [/^加载 FEA 帧\s*(\d+)\/(\d+)$/, 'Load FEA frame $1/$2'],
      [/^网格分块\s*(\d+)\/(\d+)\s*·\s*([\d,]+)\s*单元$/, 'Mesh chunk $1/$2 · $3 elements'],
      [/^播放\s*(\d+)\/(\d+)$/, 'Playback $1/$2'],
      [/^(\d+)\s*帧播放$/, '$1-frame playback'],
      [/^(\d+)\s*帧播放完成$/, '$1-frame playback completed'],
      [/^电机版本\s*(.+)$/, 'Motor revision $1'],
      [/^分析版本\s*(.+)$/, 'Analysis revision $1'],
      [/^版本\s*(.+)$/, 'Revision $1'],
      [/^已提交\s*(\d+)\s*个标准分析任务，将按 Worker \/ 许可证容量排队。$/, '$1 standard analyses were submitted and queued by worker/license capacity.'],
      [/^工程指标\s*(\d+)\/(\d+)\s*已覆盖。$/, 'Engineering metrics $1/$2 covered.'],
      [/^工程指标\s*(\d+)\/(\d+)\s*已覆盖，仍有缺口。$/, 'Engineering metrics $1/$2 covered; gaps remain.'],
    ],
    zh: [
      [/^(\d+)\s+items need review$/i, '$1 项待确认'],
      [/^(\d+)\s+validation steps$/i, '$1 个验证步骤'],
      [/^View\s+(\d+)\s+standard validation steps$/i, '查看 $1 个标准验证步骤'],
      [/^(\d+)\s+items remaining$/i, '还需处理 $1 项'],
      [/^(\d+)\s+blocking items$/i, '$1 个阻断项'],
      [/^(\d+)\s+blocking items,\s*(\d+)\s+warnings$/i, '$1 个阻断，$2 个提示'],
      [/^Load FEA frame\s*(\d+)\/(\d+)$/i, '加载 FEA 帧 $1/$2'],
      [/^Mesh chunk\s*(\d+)\/(\d+)\s*·\s*([\d,]+)\s*elements$/i, '网格分块 $1/$2 · $3 单元'],
      [/^Playback\s*(\d+)\/(\d+)$/i, '播放 $1/$2'],
      [/^(\d+)-frame playback completed$/i, '$1 帧播放完成'],
      [/^Motor revision\s*(.+)$/i, '电机版本 $1'],
      [/^Analysis revision\s*(.+)$/i, '分析版本 $1'],
      [/^Revision\s*(.+)$/i, '版本 $1'],
    ],
  };

  const replacements = {
    en: [...zhToEn.entries()].sort((a, b) => b[0].length - a[0].length),
    zh: [...enToZh.entries()].sort((a, b) => b[0].length - a[0].length),
  };

  const preserveOuterWhitespace = (source, translated) => {
    const match = String(source).match(/^(\s*)([\s\S]*?)(\s*)$/);
    return `${match?.[1] || ''}${translated}${match?.[3] || ''}`;
  };

  function applyTemplate(value, target) {
    for (const [pattern, replacement] of templates[target]) {
      if (pattern.test(value)) return value.replace(pattern, replacement);
    }
    return null;
  }

  function replaceKnownPhrases(value, target) {
    let output = value;
    const sourceHasTargetScript = target === 'en' ? hasChinese(output) : hasLatinWord(output);
    if (!sourceHasTargetScript) return output;
    for (const [source, translated] of replacements[target]) {
      // Exact labels are handled before this function.  Partial replacement is
      // deliberately limited to substantial phrases so short tokens such as
      // “失败”/“项” cannot corrupt a longer label (for example “启动FAIL”).
      if (target === 'en') {
        const cjkLength = (source.match(/[\u3400-\u9fff]/g) || []).length;
        if (cjkLength < 3) continue;
      } else {
        const words = source.match(/[A-Za-z][A-Za-z-]*/g) || [];
        const alphabeticLength = words.join('').length;
        if (alphabeticLength < 5) continue;
      }
      if (!output.includes(source)) continue;
      output = output.split(source).join(translated);
    }
    return output;
  }

  function translateString(source, target = language()) {
    const raw = String(source ?? '');
    const trimmed = raw.trim();
    if (!trimmed) return raw;
    // Motor-CAD/Python identifiers are data, not UI copy.  In V0.91.6/V0.91.7
    // partial phrase replacement could turn TorqueCalculation into Torque计算.
    // Preserve camel/Pascal/API-like tokens even when a surrounding surface forgot
    // to opt out through data-i18n-skip.
    const technicalIdentifier = /^[A-Za-z_][A-Za-z0-9_\[\]()./+%:-]*$/.test(trimmed)
      && (/[a-z0-9][A-Z]/.test(trimmed) || /[A-Z]{2,}/.test(trimmed));
    if (technicalIdentifier) return raw;
    const exact = target === 'en' ? zhToEn.get(trimmed) : enToZh.get(trimmed);
    if (exact) return preserveOuterWhitespace(raw, exact);
    const templated = applyTemplate(trimmed, target);
    if (templated) return preserveOuterWhitespace(raw, templated);
    const translated = replaceKnownPhrases(trimmed, target);
    return translated === trimmed ? raw : preserveOuterWhitespace(raw, translated);
  }

  function shouldSkip(node) {
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    return Boolean(element?.closest?.(SKIP_SELECTOR));
  }

  function translateTextNode(node) {
    if (!node || node.nodeType !== Node.TEXT_NODE || shouldSkip(node)) return;
    const raw = node.nodeValue || '';
    const previous = textState.get(node);
    const source = previous && raw === previous.rendered ? previous.source : raw;
    const rendered = translateString(source);
    textState.set(node, {source, rendered});
    if (raw !== rendered) node.nodeValue = rendered;
  }

  function translateAttributes(element) {
    if (!(element instanceof Element) || element.matches(SKIP_SELECTOR) || element.closest('[data-i18n-skip]')) return;
    const record = attrState.get(element) || {};
    for (const attribute of ATTRIBUTES) {
      if (!element.hasAttribute(attribute)) continue;
      const raw = element.getAttribute(attribute) || '';
      const previous = record[attribute];
      const source = previous && raw === previous.rendered ? previous.source : raw;
      const rendered = translateString(source);
      record[attribute] = {source, rendered};
      if (raw !== rendered) element.setAttribute(attribute, rendered);
    }
    attrState.set(element, record);
  }

  function translateTree(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root);
      return;
    }
    if (!(root instanceof Element) && root !== document && root !== document.body) return;
    if (root instanceof Element) translateAttributes(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === Node.ELEMENT_NODE && node.matches?.(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let node = walker.nextNode();
    while (node) {
      if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
      else translateAttributes(node);
      node = walker.nextNode();
    }
  }

  function applyKeys(root = document) {
    const scope = root?.querySelectorAll ? root : document;
    scope.querySelectorAll?.('[data-i18n-key]').forEach(element => {
      const row = keyCatalog[element.dataset.i18nKey];
      if (!row) return;
      const next = language() === 'en' ? row.en : row.zh;
      if (next != null) element.textContent = next;
    });
  }

  function updateLanguageControl() {
    const current = language();
    const button = document.getElementById('languageToggle');
    document.documentElement.lang = current === 'en' ? 'en' : 'zh-CN';
    document.documentElement.dataset.language = current;
    document.body?.setAttribute('data-language', current);
    if (!button) return;
    button.textContent = current === 'en' ? 'ZH' : 'EN';
    button.dataset.languageCurrent = current;
    button.setAttribute('aria-pressed', current === 'en' ? 'true' : 'false');
    button.setAttribute('aria-label', current === 'en' ? 'Switch to Chinese' : '切换到英语');
    button.title = current === 'en' ? 'Switch to Chinese' : '切换到英语';
  }

  function apply(root = document.body) {
    applyKeys(root?.ownerDocument || document);
    translateTree(root || document.body);
    updateLanguageControl();
  }

  function flushPending() {
    flushFrame = 0;
    const roots = [...pendingNodes];
    pendingNodes.clear();
    roots.forEach(translateTree);
    applyKeys(document);
    updateLanguageControl();
  }

  function queueNode(node) {
    if (!node) return;
    pendingNodes.add(node.nodeType === Node.ATTRIBUTE_NODE ? node.ownerElement : node);
    if (!flushFrame) flushFrame = requestAnimationFrame(flushPending);
  }

  function setLanguage(next, {emit = true} = {}) {
    const normalized = normalizeLanguage(next);
    if (!SUPPORTED.has(normalized)) return language();
    const previous = language();
    localStorage.setItem(STORAGE_KEY, normalized);
    apply(document.body);
    if (emit && previous !== normalized) {
      document.dispatchEvent(new CustomEvent('mcs-language-change', {detail: {language: normalized, previous}}));
      // Dynamic modules re-render in response to the event. Reconcile once more after them.
      requestAnimationFrame(() => apply(document.body));
      setTimeout(() => apply(document.body), 80);
    }
    return normalized;
  }

  function audit(root = document.body) {
    const current = language();
    const issues = [];
    root?.querySelectorAll?.('button,a,label,h1,h2,h3,h4,p,span,small,th,td,summary,option').forEach(element => {
      if (shouldSkip(element) || !element.getClientRects?.().length) return;
      const value = (element.textContent || '').replace(/\s+/g, ' ').trim();
      if (!value) return;
      if (current === 'en' && hasChinese(value)) issues.push({kind: 'CHINESE_IN_ENGLISH_UI', value: value.slice(0, 160)});
      if (current === 'zh' && !hasChinese(value) && hasLatinWord(value) && !/^(MotorCAD Studio|Motor-CAD|SPM|IPM|AFPM|BPM|IM|EMag|FEA|RPM|CSV|JSONL|DOE|Pareto|WebGL|PyMotorCAD|SQLite|RSS|PASS|STALE|NATIVE_QUALIFIED|NSGA-II|Ctrl|Esc)$/i.test(value)) {
        issues.push({kind: 'ENGLISH_IN_CHINESE_UI', value: value.slice(0, 160)});
      }
    });
    const unique = [...new Map(issues.map(row => [`${row.kind}:${row.value}`, row])).values()];
    return {language: current, passed: unique.length === 0, issue_count: unique.length, issues: unique};
  }

  window.MCS_I18N = {
    get language() { return language(); },
    t: (zh, en) => language() === 'en' ? (en || zh) : zh,
    tKey: key => {
      const row = keyCatalog[key];
      return row ? (language() === 'en' ? row.en : row.zh) : key;
    },
    translate: translateString,
    apply,
    setLanguage,
    toggle: () => setLanguage(language() === 'en' ? 'zh' : 'en'),
    audit,
    catalogSize: zhToEn.size,
  };

  document.addEventListener('DOMContentLoaded', () => {
    apply(document.body);
    const toggle = document.getElementById('languageToggle');
    if (toggle && toggle.dataset.i18nBound !== 'true') {
      toggle.dataset.i18nBound = 'true';
      toggle.addEventListener('click', event => {
        event.preventDefault();
        window.MCS_I18N.toggle();
      });
    }
    if ('MutationObserver' in window && document.body) {
      observer = new MutationObserver(records => {
        for (const record of records) {
          if (record.type === 'characterData') queueNode(record.target);
          else if (record.type === 'attributes') queueNode(record.target);
          else record.addedNodes.forEach(queueNode);
        }
      });
      observer.observe(document.body, {
        childList: true,
        characterData: true,
        subtree: true,
        attributes: true,
        attributeFilter: ATTRIBUTES,
      });
    }
  }, {once: true});
})();
