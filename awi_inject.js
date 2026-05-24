/**
 * AWI (Augmented Web Interaction) DOM injection — single source of truth.
 * Loaded by AWI_protocol.js (standalone demo) and test.py (BrowserGym agent).
 *
 * Design: reduce noise (viewport prune) + annotate visible interactives in-place.
 * Does NOT inject task-specific controls or dump full element text into labels.
 *
 * Merged from team scripts:
 *   - 팀원: viewport pruning (aria-hidden) + virtual pagination button
 *   - 재후님: aria-label metadata augmentation + onclick → role=button
 *   Plus: SVI scroll flattening, slider +/- helpers, BrowserGym bid copy, MiniWob alink
 *
 * Pipeline order:
 *   1. SVI scroll-box flattening (before pruning)
 *   2. Slider discrete +/- buttons
 *   3. MiniWob span.alink → role=link (before pruning)
 *   4. Viewport pruning (팀원; skips span.alink)
 *   4b. Un-hide span.alink targets hidden via ancestor pruning
 *   5. Metadata augmentation (재후님/script1 + bid)
 *   6. BrowserGym SOM pass
 *   7. Virtual pagination button (팀원)
 */
(function () {
    // Measure whether the document naturally scrolls BEFORE AWI Step 1 flattening.
    // Step 1 sets overflow:visible on inner containers, which pushes their content
    // into the normal document flow and artificially inflates scrollHeight.
    // If we measured docScrolls AFTER flattening, we would incorrectly add
    // window-scroll buttons for pages that actually fit in one viewport
    // (e.g. MiniWob social-media: tweet list is flat → scrollHeight grows → grey BG).
    var _docNaturallyScrolls =
        (document.documentElement.scrollHeight || 0) >
        (window.innerHeight || document.documentElement.clientHeight) + 20;

    function stripAwiTags(text) {
        return (text || '').replace(/\s*\[AWI:[^\]]*\]/g, '').replace(/\n/g, ' ').trim();
    }

    // Bug fix: "fully inside" was too strict — container spans or large-font elements
    // can have their bounding rect extend a few pixels beyond vh/vw in certain
    // BrowserGym viewport configurations, causing them to be incorrectly pruned
    // even when the entire page fits in one viewport.
    // Now: hide only elements with NO overlap with the viewport at all.
    function isInViewport(el) {
        var rect = el.getBoundingClientRect();
        var vh = window.innerHeight || document.documentElement.clientHeight;
        var vw = window.innerWidth || document.documentElement.clientWidth;
        return (
            rect.bottom > 0 &&
            rect.right > 0 &&
            rect.top < vh &&
            rect.left < vw
        );
    }

    // 재후님: build AWI tags (aria-label, not aria-description)
    // Only include tag= for semantically meaningful elements.
    // Structural tags (span, a, div, li, …) carry no extra info for the LLM.
    var SEMANTIC_TAGS = { input: 1, button: 1, select: 1, textarea: 1 };
    function buildAwiMeta(el, tag) {
        var tags = '[AWI: clickable=True]';
        if (SEMANTIC_TAGS[tag]) tags = '[AWI: tag=' + tag + '] ' + tags;
        var bid = el.getAttribute('bid');
        if (bid) tags += ' [AWI: bid=' + bid + ']';
        if (tag === 'input' && el.type) tags += ' [AWI: input_type=' + el.type + ']';
        // Bug fix: expose live input value so LLM can confirm its own fill() actions.
        if (tag === 'input' && el.value) tags += ' [AWI: value=' + el.value + ']';
        // Names avoid "scroll*" so the LLM does not map these to scroll(delta_x, delta_y).
        if (tag === 'textarea' && el.scrollHeight > el.clientHeight) {
            tags += ' [AWI: clipped_content=true]';
            tags += ' [AWI: view_offset=' + el.scrollTop + ']';
            tags += ' [AWI: view_offset_max=' + (el.scrollHeight - el.clientHeight) + ']';
        }
        if (el.hasAttribute('data-awi-flattened')) {
            tags += ' [AWI: scroll_flattened=true]';
        }
        // Add HTML class names so LLM can infer semantics from class (e.g. class=retweet).
        var cls = typeof el.className === 'string' ? el.className.trim().replace(/\s+/g, ' ') : '';
        if (cls) tags += ' [AWI: class=' + cls + ']';
        return tags;
    }

    // Do not put full textarea/value text into aria-label (that duplicates the whole document).
    function ariaLabelBase(el, tag) {
        if (tag === 'textarea') {
            return stripAwiTags(el.id || el.name || 'textarea');
        }
        if (tag === 'input') {
            // Bug fix: prioritize el.value over aria-label.
            return stripAwiTags(el.value || el.getAttribute('aria-label') || '');
        }
        return stripAwiTags(
            el.getAttribute('aria-label') || el.innerText || el.value || ''
        );
    }

    function applyAwiLabel(el, tag) {
        if ((el.hasAttribute('onclick') || el.hasAttribute('data-awi-clickable')) && tag !== 'button' && tag !== 'a') {
            el.setAttribute('role', 'button');
        }
        var base = ariaLabelBase(el, tag);
        el.setAttribute('aria-label', (base + ' ' + buildAwiMeta(el, tag)).trim());
    }

    // ── 1. SVI: flatten inner scroll containers ───────────────────────────────
    var scrollBoxes = document.querySelectorAll(
        'div, ul, tbody, section, [role="listbox"]'
    );
    for (var s = 0; s < scrollBoxes.length; s++) {
        var box = scrollBoxes[s];
        var style = window.getComputedStyle(box);
        if (
            (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
            box.scrollHeight > box.clientHeight
        ) {
            box.style.overflow = 'visible';
            box.style.maxHeight = 'none';
            box.style.height = 'auto';
            box.setAttribute('data-awi-flattened', 'true');
        }
    }

    // ── 2. SVI: discrete slider controls ────────────────────────────────────
    var sliders = document.querySelectorAll('input[type="range"], [role="slider"]');
    for (var sl = 0; sl < sliders.length; sl++) {
        var slider = sliders[sl];
        var decBtn = document.createElement('button');
        decBtn.innerText = '[-] Decrease [AWI: slider_dec_' + sl + ']';
        decBtn.setAttribute('aria-label', '[-] Decrease [AWI: slider_dec_' + sl + ']');
        var incBtn = document.createElement('button');
        incBtn.innerText = '[+] Increase [AWI: slider_inc_' + sl + ']';
        incBtn.setAttribute('aria-label', '[+] Increase [AWI: slider_inc_' + sl + ']');
        if (slider.parentNode) {
            slider.parentNode.insertBefore(decBtn, slider);
            slider.parentNode.insertBefore(incBtn, slider.nextSibling);
        }
    }

    // ── 3. [MiniWob] promote word links BEFORE pruning (span.alink) ───────────
    // #area span[bid] removed: it matched ALL bid-bearing spans including decorative
    // .addition-block elements, flooding every task with tag=span noise.
    var wordLinks = document.querySelectorAll('span.alink');
    for (var w = 0; w < wordLinks.length; w++) {
        var wl = wordLinks[w];
        var isAlink = wl.classList && wl.classList.contains('alink');
        var wlStyle = window.getComputedStyle(wl);
        if (!isAlink && wlStyle.cursor !== 'pointer') {
            continue;
        }
        wl.removeAttribute('aria-hidden');
        wl.setAttribute('role', 'link');
        var word = stripAwiTags(wl.innerText || wl.textContent || '');
        wl.setAttribute('aria-label', (word + ' ' + buildAwiMeta(wl, 'span')).trim());
    }

    // ── 4. [팀원] viewport pruning — never hide span.alink (click-tab targets) ─
    var allElements = document.querySelectorAll(
        'button, a, input, textarea, select, div, span, [role="button"]'
    );
    for (var i = 0; i < allElements.length; i++) {
        var el = allElements[i];
        if (el.classList && el.classList.contains('alink')) {
            continue;
        }
        if (!isInViewport(el)) {
            el.setAttribute('aria-hidden', 'true');
        }
    }

    // ── 4b. Un-hide MiniWob word links if an ancestor was pruned ─────────────
    var alinks = document.querySelectorAll('span.alink');
    for (var u = 0; u < alinks.length; u++) {
        var node = alinks[u];
        node.removeAttribute('aria-hidden');
        var parent = node.parentElement;
        while (parent) {
            parent.removeAttribute('aria-hidden');
            parent = parent.parentElement;
        }
    }

    // ── 4c. [Non-standard] Promote CSS icon span/div bid elements ────────────────
    // MiniWob (e.g. social-media) renders icon buttons via CSS content:url()
    // on plain spans — no onclick, no role, no cursor:pointer in base state
    // (cursor:pointer is only in :hover selector, invisible to getComputedStyle).
    // CSS `content: url(...)` on a non-pseudo element reliably identifies CSS icon
    // buttons (e.g. .reply { content:url(reply.png); }).
    // Also handles cursor:pointer for sites that set it in the base state (standard).
    var iconCandidates = document.querySelectorAll(
        'span[bid]:not([aria-hidden]):not(.alink), ' +
        'div[bid]:not([aria-hidden])'
    );
    for (var p = 0; p < iconCandidates.length; p++) {
        var pc = iconCandidates[p];
        if (pc.hasAttribute('role')) continue; // already promoted in a prior step
        var pcStyle = window.getComputedStyle(pc);
        var isCssIcon = (pcStyle.content || '').indexOf('url') !== -1;
        var isPointer = pcStyle.cursor === 'pointer';
        if (isCssIcon || isPointer) {
            pc.setAttribute('role', 'button');
            applyAwiLabel(pc, pc.tagName.toLowerCase());
        }
    }

    // ── 5. [재후님] metadata on visible interactives (+ bid for BrowserGym) ─
    // span[bid] removed: non-interactive bid spans are handled in step 5b below.
    var visibleInteractiveElements = document.querySelectorAll(
        'a:not([aria-hidden]), button:not([aria-hidden]), ' +
        'input:not([aria-hidden]), textarea:not([aria-hidden]), ' +
        'select:not([aria-hidden]), ' +
        '[onclick]:not([aria-hidden]), ' +
        '[data-awi-clickable]:not([aria-hidden])'
    );
    for (var j = 0; j < visibleInteractiveElements.length; j++) {
        var el = visibleInteractiveElements[j];
        applyAwiLabel(el, el.tagName.toLowerCase());
    }

    // ── 5b. Non-interactive bid containers → graphic_object ──────────────────
    // BrowserGym stamps bid on all elements including decorative containers
    // (span, div). These are NOT clickable — label them as graphic objects so
    // the LLM can see them in the structure without mistaking them for targets.
    // No clickable=True, no bid in the label (not an action target).
    var containerEls = document.querySelectorAll(
        'span[bid]:not([aria-hidden]):not(.alink):not([onclick]):not([data-awi-clickable]), ' +
        'div[bid]:not([aria-hidden]):not([data-awi-clickable])'
    );
    for (var c = 0; c < containerEls.length; c++) {
        var cel = containerEls[c];
        // Skip if already promoted to an interactive role (e.g. span.alink → role=link)
        if (cel.hasAttribute('role')) continue;
        // Skip if already labeled by step 5 (interactive elements)
        var existingLabel = cel.getAttribute('aria-label') || '';
        if (existingLabel.indexOf('[AWI: clickable=True]') !== -1) continue;
        var celCls = typeof cel.className === 'string' ? cel.className.trim().replace(/\s+/g, ' ') : '';
        cel.setAttribute('aria-label', '[AWI: graphic_object]' + (celCls ? ' [AWI: class=' + celCls + ']' : ''));
    }

    // ── 6. BrowserGym SOM: elements flagged set_of_marks=1 ────────────────────
    var somEls = document.querySelectorAll(
        '[browsergym_set_of_marks="1"]:not([aria-hidden])'
    );
    for (var k = 0; k < somEls.length; k++) {
        var el2 = somEls[k];
        var label = el2.getAttribute('aria-label') || '';
        if (label.indexOf('bid=') !== -1 || label.indexOf('[AWI: bid=') !== -1) {
            continue;
        }
        el2.setAttribute('role', 'button');
        applyAwiLabel(el2, el2.tagName.toLowerCase());
    }

    // ── 6b. Parent-child deduplication ───────────────────────────────────────────
    // Problem: BrowserGym SOM stamps bid on BOTH a container element and its inner
    // interactive child (e.g. outer `card hidden` div + inner `card-value` span).
    // All labeling steps above (4c, 5, 6) can independently promote both to buttons.
    // The a11y tree returns the parent first, so the LLM always clicks the container —
    // which does NOT trigger the game's JS handler → DOM never changes → snapshot frozen.
    //
    // Fix (two-pass): after all labeling is done, demote any [AWI: clickable=True] element
    // whose subtree already contains another [AWI: clickable=True] element.
    // The parent is a structural container; only the leaf child is the real click target.
    var clickableEls = document.querySelectorAll('[aria-label*="[AWI: clickable=True]"]:not([aria-hidden])');
    for (var d = 0; d < clickableEls.length; d++) {
        var dup = clickableEls[d];
        if (dup.querySelector('[aria-label*="[AWI: clickable=True]"]') !== null) {
            var dupCls = typeof dup.className === 'string' ? dup.className.trim().replace(/\s+/g, ' ') : '';
            dup.removeAttribute('role');
            dup.setAttribute('aria-label', '[AWI: graphic_object]' + (dupCls ? ' [AWI: class=' + dupCls + ']' : ''));
        }
    }

    // ── 7. [팀원] virtual pagination — only when the document naturally scrolled ─
    // Use the pre-flatten measurement to avoid false positives from Step 1 inflate.
    if (_docNaturallyScrolls) {
        // Next Page button — shown whenever the document can scroll
        if (!document.querySelector('[data-awi-next]')) {
            var virtualNextBtn = document.createElement('button');
            virtualNextBtn.setAttribute('data-awi-next', '1');
            virtualNextBtn.innerText = 'Next Page [AWI: action_id=999]';
            virtualNextBtn.setAttribute('aria-label', 'Next Page [AWI: scroll_down]');
            virtualNextBtn.style.position = 'fixed';
            virtualNextBtn.style.bottom = '10px';
            virtualNextBtn.style.right = '10px';
            virtualNextBtn.style.zIndex = '9999';
            virtualNextBtn.style.backgroundColor = '#d9534f';
            virtualNextBtn.style.color = 'white';
            virtualNextBtn.style.fontWeight = 'bold';
            virtualNextBtn.style.cursor = 'pointer';
            virtualNextBtn.onclick = function () {
                window.scrollBy({ top: window.innerHeight * 0.8, behavior: 'smooth' });
            };
            document.body.appendChild(virtualNextBtn);
        }
        // Previous Page button — shown only when not already at the top
        if (!document.querySelector('[data-awi-prev]') && window.scrollY > 20) {
            var virtualPrevBtn = document.createElement('button');
            virtualPrevBtn.setAttribute('data-awi-prev', '1');
            virtualPrevBtn.innerText = 'Previous Page [AWI: action_id=998]';
            virtualPrevBtn.setAttribute('aria-label', 'Previous Page [AWI: scroll_up]');
            virtualPrevBtn.style.position = 'fixed';
            virtualPrevBtn.style.bottom = '50px';
            virtualPrevBtn.style.right = '10px';
            virtualPrevBtn.style.zIndex = '9999';
            virtualPrevBtn.style.backgroundColor = '#5bc0de';
            virtualPrevBtn.style.color = 'white';
            virtualPrevBtn.style.fontWeight = 'bold';
            virtualPrevBtn.style.cursor = 'pointer';
            virtualPrevBtn.onclick = function () {
                window.scrollBy({ top: -window.innerHeight * 0.8, behavior: 'smooth' });
            };
            document.body.appendChild(virtualPrevBtn);
        }
    }
})();
