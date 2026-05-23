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
    function stripAwiTags(text) {
        return (text || '').replace(/\s*\[AWI:[^\]]*\]/g, '').replace(/\n/g, ' ').trim();
    }

    // 팀원/script1+2: element fully inside viewport
    function isFullyInViewport(el) {
        var rect = el.getBoundingClientRect();
        var vh = window.innerHeight || document.documentElement.clientHeight;
        var vw = window.innerWidth || document.documentElement.clientWidth;
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= vh &&
            rect.right <= vw
        );
    }

    // 재후님: build AWI tags (aria-label, not aria-description)
    function buildAwiMeta(el, tag) {
        var tags = '[AWI: tag=' + tag + '] [AWI: clickable=True]';
        var bid = el.getAttribute('bid');
        if (bid) tags += ' [AWI: bid=' + bid + ']';
        if (tag === 'input' && el.type) tags += ' [AWI: input_type=' + el.type + ']';
        // Names avoid "scroll*" so the LLM does not map these to scroll(delta_x, delta_y).
        if (tag === 'textarea' && el.scrollHeight > el.clientHeight) {
            tags += ' [AWI: clipped_content=true]';
            tags += ' [AWI: view_offset=' + el.scrollTop + ']';
            tags += ' [AWI: view_offset_max=' + (el.scrollHeight - el.clientHeight) + ']';
        }
        if (el.hasAttribute('data-awi-flattened')) {
            tags += ' [AWI: scroll_flattened=true]';
        }
        return tags;
    }

    // Do not put full textarea/value text into aria-label (that duplicates the whole document).
    function ariaLabelBase(el, tag) {
        if (tag === 'textarea') {
            return stripAwiTags(el.id || el.name || 'textarea');
        }
        return stripAwiTags(
            el.getAttribute('aria-label') || el.innerText || el.value || ''
        );
    }

    function applyAwiLabel(el, tag) {
        if (el.hasAttribute('onclick') && tag !== 'button' && tag !== 'a') {
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
    var wordLinks = document.querySelectorAll('span.alink, #area span[bid]');
    for (var w = 0; w < wordLinks.length; w++) {
        var wl = wordLinks[w];
        var isAlink = wl.classList && wl.classList.contains('alink');
        var style = window.getComputedStyle(wl);
        if (!isAlink && style.cursor !== 'pointer') {
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
        if (!isFullyInViewport(el)) {
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

    // ── 5. [재후님] metadata on visible interactives (+ bid for BrowserGym) ─
    var visibleInteractiveElements = document.querySelectorAll(
        'a:not([aria-hidden]), button:not([aria-hidden]), ' +
        'input:not([aria-hidden]), textarea:not([aria-hidden]), ' +
        'select:not([aria-hidden]), span[bid]:not([aria-hidden]), ' +
        '[onclick]:not([aria-hidden])'
    );
    for (var j = 0; j < visibleInteractiveElements.length; j++) {
        var el = visibleInteractiveElements[j];
        applyAwiLabel(el, el.tagName.toLowerCase());
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

    // ── 7. [팀원] virtual pagination — only when the document itself scrolls ───
    var docScrolls =
        (document.documentElement.scrollHeight || 0) >
        (window.innerHeight || document.documentElement.clientHeight) + 20;
    if (docScrolls && !document.querySelector('[data-awi-next]')) {
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
            window.scrollBy({
                top: window.innerHeight * 0.8,
                behavior: 'smooth',
            });
        };
        document.body.appendChild(virtualNextBtn);
    }
})();
