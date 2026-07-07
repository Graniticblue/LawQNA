// ── 익명 사용자 식별 쿠키 (chat history용) ──────────────────
// 로그인 없이 브라우저별로 대화 내역을 사이드바에 유지하기 위해,
// anon_id 쿠키가 없으면 즉시 발급하고 1회 새로고침해 인증에 반영한다.
(function ensureAnonId() {
    const has = document.cookie.split('; ').some(c => c.startsWith('anon_id='));
    if (!has) {
        const rnd = (crypto && crypto.randomUUID)
            ? crypto.randomUUID().replace(/-/g, '').slice(0, 16)
            : (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
        document.cookie = 'anon_id=anon_' + rnd + '; path=/; max-age=' + (60 * 60 * 24 * 365) + '; SameSite=Lax';
        location.reload();
    }
})();

(function () {
    // ── 로고 ────────────────────────────────────────────────
    const LOGO_WRAP_ID = 'usun-logo-wrap';

    function hasMessages() {
        // Chainlit 메시지 요소 감지 (step, message 컨테이너)
        return document.querySelectorAll('[data-testid="step"], [class*="MessageContent"], [class*="message-content"]').length > 0;
    }

    function removeLogo() {
        const wrap = document.getElementById(LOGO_WRAP_ID);
        if (wrap) wrap.remove();
    }

    function insertLogo() {
        if (document.getElementById(LOGO_WRAP_ID)) return;
        if (hasMessages()) return;  // 메시지 있으면 삽입 안 함

        const submitBtn = document.getElementById('chat-submit');
        if (!submitBtn) return;

        const inputBox = submitBtn.parentElement?.parentElement?.parentElement;
        if (!inputBox || !inputBox.parentNode) return;

        const wrap = document.createElement('div');
        wrap.id = LOGO_WRAP_ID;
        wrap.style.cssText = [
            'width: 100%',
            'max-width: ' + inputBox.getBoundingClientRect().width + 'px',
            'margin: 0 auto 10px auto',
            'display: flex',
            'justify-content: center',
        ].join(';');

        const img = document.createElement('img');
        img.id = 'usun-logo';
        img.src = 'https://www.usun.co.kr/assets/images/logo.png';
        img.alt = 'usun';
        img.style.cssText = 'max-height: 52px; max-width: 200px; object-fit: contain;';

        wrap.appendChild(img);
        inputBox.parentNode.insertBefore(wrap, inputBox);
    }

    // 추천질문(starters)을 한 줄에 가로 배치 (기본은 두 줄로 wrap됨)
    function layoutStarters() {
        const btns = Array.prototype.slice.call(document.querySelectorAll('button'))
            .filter(function (b) {
                return b.className.indexOf('rounded-3xl') !== -1 && b.querySelector('p.truncate');
            });
        if (btns.length >= 2 && btns[0].parentElement) {
            const c = btns[0].parentElement;
            c.style.flexWrap = 'nowrap';
            c.style.overflowX = 'auto';
            c.style.justifyContent = 'flex-start';
            // 버튼이 줄어들어 라벨이 잘리지 않도록 가로스크롤 허용
            btns.forEach(function (b) { b.style.flexShrink = '0'; });
        }
    }

    // ── 내장 법령 목록: 상단 헤더 버튼(Readme 옆) + 모달 팝업 ──────
    function showLawListModal() {
        var ov = document.getElementById('law-list-modal');
        if (ov) { ov.style.display = 'flex'; return; }
        ov = document.createElement('div');
        ov.id = 'law-list-modal';
        ov.innerHTML =
            '<div class="law-list-box">' +
            '<button class="law-list-close" aria-label="닫기">✕</button>' +
            '<div class="law-list-content">불러오는 중…</div>' +
            '</div>';
        ov.addEventListener('click', function (e) { if (e.target === ov) ov.style.display = 'none'; });
        ov.querySelector('.law-list-close').onclick = function () { ov.style.display = 'none'; };
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { var m = document.getElementById('law-list-modal'); if (m) m.style.display = 'none'; }
        });
        document.body.appendChild(ov);
        fetch('/law-list')
            .then(function (r) { return r.text(); })
            .then(function (h) { ov.querySelector('.law-list-content').innerHTML = h; })
            .catch(function () { ov.querySelector('.law-list-content').innerText = '목록을 불러오지 못했습니다.'; });
    }

    // ── 업로드 캐시: 헤더 버튼 + 모달 (목록·개별 삭제) ─────────────
    function loadUploadCache(ov) {
        fetch('/upload-cache')
            .then(function (r) { return r.text(); })
            .then(function (h) { ov.querySelector('.law-list-content').innerHTML = h; })
            .catch(function () { ov.querySelector('.law-list-content').innerText = '목록을 불러오지 못했습니다.'; });
    }

    function showUploadModal() {
        var ov = document.getElementById('upload-cache-modal');
        if (ov) { ov.style.display = 'flex'; loadUploadCache(ov); return; }
        ov = document.createElement('div');
        ov.id = 'upload-cache-modal';
        ov.innerHTML =
            '<div class="law-list-box">' +
            '<button class="law-list-close" aria-label="닫기">✕</button>' +
            '<div class="law-list-content">불러오는 중…</div>' +
            '</div>';
        ov.addEventListener('click', function (e) {
            if (e.target === ov) { ov.style.display = 'none'; return; }
            var b = e.target.closest && e.target.closest('.law-list-del');
            if (b) {   // 삭제 버튼 (이벤트 위임)
                b.disabled = true; b.textContent = '삭제 중…';
                fetch('/upload-cache/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ law_name: b.dataset.law }),
                })
                    .then(function () { loadUploadCache(ov); })
                    .catch(function () { b.disabled = false; b.textContent = '삭제'; });
            }
        });
        ov.querySelector('.law-list-close').onclick = function () { ov.style.display = 'none'; };
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { var m = document.getElementById('upload-cache-modal'); if (m) m.style.display = 'none'; }
        });
        document.body.appendChild(ov);
        loadUploadCache(ov);
    }

    function insertLawListButton() {
        try {
            if (document.getElementById('law-list-btn')) return;
            // 'Readme' 버튼/링크 바로 앞에 삽입 (파란 버전에서 정상 동작한 방식)
            var readme = Array.prototype.slice.call(document.querySelectorAll('button, a'))
                .find(function (el) { return el.textContent.trim() === 'Readme'; });
            if (!readme || !readme.parentElement) return;  // 헤더 준비 전이면 다음 mutation에 재시도
            var btn = document.createElement('button');
            btn.id = 'law-list-btn';
            btn.type = 'button';
            btn.textContent = '내장 법령 목록';
            btn.className = 'law-list-btn';
            btn.onclick = showLawListModal;
            readme.parentElement.insertBefore(btn, readme);
            // 업로드 자료 버튼 (내장 법령 목록과 Readme 사이)
            var ub = document.createElement('button');
            ub.id = 'upload-cache-btn';
            ub.type = 'button';
            ub.textContent = '업로드 캐시';
            ub.className = 'law-list-btn';
            ub.onclick = showUploadModal;
            readme.parentElement.insertBefore(ub, readme);
            // 등간격화: Readme와 우측 인접 항목(아이콘) 사이 네이티브 간격을 측정해
            // 내 버튼 간격을 동일하게 맞춘다. (측정 실패 시 CSS margin-right 폴백)
            requestAnimationFrame(function () {
                try {
                    var r = readme.getBoundingClientRect();
                    var right = Array.prototype.slice.call(readme.parentElement.children)
                        .filter(function (el) {
                            return el !== btn && el.getBoundingClientRect().left >= r.right - 1;
                        })
                        .sort(function (a, b) {
                            return a.getBoundingClientRect().left - b.getBoundingClientRect().left;
                        })[0];
                    if (right) {
                        var gap = right.getBoundingClientRect().left - r.right;
                        if (gap > 0 && gap < 80) btn.style.marginRight = gap + 'px';
                    }
                } catch (e) { }
            });
        } catch (e) { /* DOM 변동 중 실패는 무시(다음 mutation에 재시도) */ }
    }

    // ── 왼쪽 대화 이력 사이드바: 드래그 리사이즈 ───────────────────
    // shadcn Sidebar는 --sidebar-width를 .group/sidebar-wrapper에 인라인(비-important)
    // 지정 → 우리가 만든 <style> 태그(문서 마지막에 삽입돼 동일 !important끼리는
    // 나중 규칙이 이김)로 매 드래그마다 값을 덮어써 실시간 리사이즈를 구현한다.
    var SB_MIN = 220, SB_MAX = 560, SB_KEY = 'sidebar_width_px';

    function sidebarStyleEl() {
        var el = document.getElementById('sidebar-resize-style');
        if (!el) {
            el = document.createElement('style');
            el.id = 'sidebar-resize-style';
            document.head.appendChild(el);
        }
        return el;
    }

    function setSidebarWidthPx(px) {
        px = Math.max(SB_MIN, Math.min(SB_MAX, Math.round(px)));
        sidebarStyleEl().textContent =
            '.group\\/sidebar-wrapper{--sidebar-width:' + px + 'px !important}';
        return px;
    }

    (function restoreSidebarWidth() {
        try {
            var saved = parseInt(localStorage.getItem(SB_KEY), 10);
            if (saved) setSidebarWidthPx(saved);
        } catch (e) { /* localStorage 불가(프라이빗 모드 등) — 기본값 유지 */ }
    })();

    function insertSidebarResizeHandle() {
        try {
            var inner = document.querySelector('[data-sidebar="sidebar"]');
            var panel = inner && inner.parentElement;   // fixed, width: var(--sidebar-width)
            if (!panel) return;
            var handle = document.getElementById('sidebar-resize-handle');

            // 접힘(icon rail, ~48px)·모바일 숨김 상태에선 핸들 숨김 — 그 상태는 리사이즈 대상 아님
            if (panel.getBoundingClientRect().width < 100) {
                if (handle) handle.style.display = 'none';
                return;
            }

            if (!handle) {
                handle = document.createElement('div');
                handle.id = 'sidebar-resize-handle';
                panel.style.position = panel.style.position || 'fixed';
                panel.appendChild(handle);

                var dragging = false, startX = 0, startW = 0, lastPx = 0;
                handle.addEventListener('mousedown', function (e) {
                    dragging = true;
                    startX = e.clientX;
                    startW = panel.getBoundingClientRect().width;
                    lastPx = startW;
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                    e.preventDefault();
                });
                document.addEventListener('mousemove', function (e) {
                    if (!dragging) return;
                    lastPx = setSidebarWidthPx(startW + (e.clientX - startX));
                });
                document.addEventListener('mouseup', function () {
                    if (!dragging) return;
                    dragging = false;
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                    try { localStorage.setItem(SB_KEY, String(lastPx)); } catch (e) { }
                });
            }
            handle.style.display = 'block';
        } catch (e) { /* 다음 mutation에 재시도 */ }
    }

    function update() {
        if (hasMessages()) {
            removeLogo();
        } else {
            insertLogo();
        }
        layoutStarters();
        insertLawListButton();
        insertSidebarResizeHandle();
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();

// ── 드래그-질문: 답변 텍스트를 선택하면 '질문' 버튼 → 인용으로 입력창 삽입 ──
(function () {
    var MAX_QUOTE = 1200;

    var btn = null;
    function getBtn() {
        if (btn) return btn;
        btn = document.createElement('button');
        btn.id = 'quote-ask-btn';
        btn.type = 'button';
        btn.textContent = '💬 질문';
        btn.style.display = 'none';
        // mousedown 시 기본동작을 막아 사용자의 텍스트 선택이 풀리지 않게 함
        btn.addEventListener('mousedown', function (e) { e.preventDefault(); e.stopPropagation(); });
        btn.addEventListener('click', onQuoteClick);
        document.body.appendChild(btn);
        return btn;
    }

    function hideBtn() { if (btn) btn.style.display = 'none'; }

    function selectedTextInMessage() {
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
        var text = sel.toString().trim();
        if (text.length < 4) return null;
        // 메시지(답변/질문) 영역 안의 선택만 대상 — 입력창·사이드바·모달 선택은 제외
        var node = sel.anchorNode;
        var el = node && (node.nodeType === 1 ? node : node.parentElement);
        if (!el) return null;
        if (el.closest('#chat-input, #law-list-modal, #upload-cache-modal')) return null;
        if (!el.closest('[data-testid="step"], [class*="MessageContent"], [class*="message-content"]')) return null;
        return { text: text, range: sel.getRangeAt(0) };
    }

    function onMouseUp() {
        // click 직후 selection 갱신이 끝난 뒤 판정
        setTimeout(function () {
            var found = selectedTextInMessage();
            if (!found) { hideBtn(); return; }
            var rect = found.range.getBoundingClientRect();
            var b = getBtn();
            b.style.display = 'block';
            // 선택 영역 아래 중앙에 배치 (position: fixed — 뷰포트 기준)
            var left = Math.min(Math.max(rect.left + rect.width / 2 - 36, 8),
                                window.innerWidth - 90);
            var top = Math.min(rect.bottom + 8, window.innerHeight - 44);
            b.style.left = left + 'px';
            b.style.top = top + 'px';
        }, 0);
    }

    function onQuoteClick() {
        var found = selectedTextInMessage();
        hideBtn();
        if (!found) return;
        var text = found.text;
        if (text.length > MAX_QUOTE) text = text.slice(0, MAX_QUOTE) + '…';
        // 마크다운 인용 형식으로 정리 (여러 줄이면 각 줄에 > 접두)
        var quoted = text.split('\n')
            .map(function (l) { return '> ' + l.trim(); })
            .filter(function (l) { return l !== '>'; })
            .join('\n') + '\n\n';

        var input = document.getElementById('chat-input');
        if (!input) return;
        input.focus();
        // 캐럿을 입력창 끝으로 이동 후 삽입 — execCommand('insertText')는
        // input 이벤트를 발생시켜 React(contenteditable) 상태에도 반영된다.
        var range = document.createRange();
        range.selectNodeContents(input);
        range.collapse(false);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand('insertText', false, quoted);
        window.getSelection().removeAllRanges();
    }

    document.addEventListener('mouseup', onMouseUp);
    document.addEventListener('mousedown', function (e) {
        if (!btn || e.target === btn) return;
        hideBtn();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') hideBtn();
    });
    window.addEventListener('scroll', hideBtn, true);
})();
