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
        // 카드 그리드가 있으면 그 위에(로고 → 그리드 → 입력창 순), 없으면 입력창 위에
        var anchor = document.getElementById('usun-starter-grid') || inputBox;
        inputBox.parentNode.insertBefore(wrap, anchor);
    }

    // ── 추천질문 → 가운데 카드 그리드 (6개, 1/1/2/2 · 유형 딱지 + 제목) ──────
    // chainlit이 렌더한 네이티브 스타터 버튼은 숨기고, 그 라벨을 읽어 카드 그리드를
    // 새로 만든다. 카드 클릭은 라벨이 일치하는 네이티브 버튼의 .click()에 위임 →
    // 전송 동작은 chainlit 것 그대로라 안정적. 유형(딱지)은 /starters-meta에서 받는다.
    var _startersMeta = null, _metaFetched = false;
    function loadStartersMeta() {
        if (_metaFetched) return;
        _metaFetched = true;
        fetch('/starters-meta')
            .then(function (r) { return r.json(); })
            .then(function (m) {
                _startersMeta = m || {};
                var g = document.getElementById('usun-starter-grid');
                if (g) g.remove();   // 딱지 포함해 다음 update에 재빌드
            })
            .catch(function () { _startersMeta = {}; });
    }

    function nativeStarterButtons() {
        return Array.prototype.slice.call(document.querySelectorAll('button'))
            .filter(function (b) {
                return b.className.indexOf('rounded-3xl') !== -1 && b.querySelector('p.truncate');
            });
    }

    function starterLabel(btn) {
        var p = btn.querySelector('p.truncate');
        return ((p ? p.textContent : btn.textContent) || '').trim();
    }

    function removeStarterGrid() {
        var g = document.getElementById('usun-starter-grid');
        if (g) g.remove();
    }

    function layoutStarterGrid() {
        var nat = nativeStarterButtons();
        if (nat.length < 1) { removeStarterGrid(); return; }   // 대화 시작 등 — 불필요

        var labels = nat.map(starterLabel);
        var sig = labels.join('|');
        var grid = document.getElementById('usun-starter-grid');
        if (grid && grid.dataset.sig === sig) {
            // 이미 동일 구성 — 네이티브 컨테이너 숨김만 유지
            if (nat[0].parentElement) nat[0].parentElement.classList.add('usun-native-starters-hidden');
            return;
        }
        if (grid) grid.remove();

        var meta = _startersMeta || {};
        grid = document.createElement('div');
        grid.id = 'usun-starter-grid';
        grid.dataset.sig = sig;

        labels.forEach(function (label) {
            var card = document.createElement('button');
            card.type = 'button';
            card.className = 'usun-card';
            var type = meta[label] || '';
            if (type) {
                var chip = document.createElement('span');
                chip.className = 'usun-card-chip';
                chip.setAttribute('data-type', type);
                chip.textContent = type;
                card.appendChild(chip);
            }
            var title = document.createElement('span');
            title.className = 'usun-card-title';
            title.textContent = label;
            card.appendChild(title);
            // 클릭 위임: 클릭 시점에 라벨로 네이티브 버튼을 재탐색해 .click()
            card.addEventListener('click', function () {
                var target = nativeStarterButtons().filter(function (b) {
                    return starterLabel(b) === label;
                })[0];
                if (target) target.click();
            });
            grid.appendChild(card);
        });

        // 입력창 위(로고 아래)에 삽입
        var submitBtn = document.getElementById('chat-submit');
        var inputBox = submitBtn && submitBtn.parentElement
            && submitBtn.parentElement.parentElement
            && submitBtn.parentElement.parentElement.parentElement;
        if (inputBox && inputBox.parentNode) {
            inputBox.parentNode.insertBefore(grid, inputBox);
        } else if (nat[0].parentElement && nat[0].parentElement.parentNode) {
            nat[0].parentElement.parentNode.insertBefore(grid, nat[0].parentElement);
        }
        // 네이티브 스타터 컨테이너 숨김 (버튼은 .click() 위임용으로 DOM에 남김)
        if (nat[0].parentElement) nat[0].parentElement.classList.add('usun-native-starters-hidden');
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

    // 파일을 채팅 없이 업로드 캐시에 등록 (질문 입력 불필요)
    function uploadCacheFile(ov, file) {
        var status = ov.querySelector('#upload-add-status');
        if (!file) return;
        if (!/\.pdf$/i.test(file.name)) { status.textContent = 'PDF 파일만 등록할 수 있습니다.'; return; }
        status.textContent = '⏳ 업로드·인덱싱 중… (' + file.name + ')';
        var fd = new FormData();
        fd.append('file', file);
        fetch('/upload-cache/add', { method: 'POST', body: fd })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (res) {
                if (!res.ok || res.d.error) {
                    status.textContent = '✗ ' + (res.d.error || '등록 실패');
                    return;
                }
                status.textContent = '✓ 「' + res.d.law_name + '」 등록됨 (' + res.d.chunks + '개 청크)';
                loadUploadCache(ov);   // 목록 새로고침
            })
            .catch(function () { status.textContent = '✗ 업로드 실패 (네트워크)'; });
    }

    function showUploadModal() {
        var ov = document.getElementById('upload-cache-modal');
        if (ov) { ov.style.display = 'flex'; loadUploadCache(ov); return; }
        ov = document.createElement('div');
        ov.id = 'upload-cache-modal';
        ov.innerHTML =
            '<div class="law-list-box">' +
            '<button class="law-list-close" aria-label="닫기">✕</button>' +
            '<div class="upload-add-bar">' +
            '<label class="upload-add-btn" for="upload-add-input">＋ PDF 파일 추가</label>' +
            '<input type="file" id="upload-add-input" accept="application/pdf,.pdf" hidden />' +
            '<input type="file" id="upload-replace-input" accept="application/pdf,.pdf" hidden />' +
            '<span id="upload-add-status" class="upload-add-status">지역조례와 별표를 별도로 등록합니다.</span>' +
            '</div>' +
            '<div class="law-list-content">불러오는 중…</div>' +
            '</div>';
        ov.addEventListener('click', function (e) {
            if (e.target === ov) { ov.style.display = 'none'; return; }
            // 삭제
            var b = e.target.closest && e.target.closest('.law-list-del');
            if (b) {
                b.disabled = true; b.textContent = '삭제 중…';
                fetch('/upload-cache/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ law_name: b.dataset.law }),
                })
                    .then(function () { loadUploadCache(ov); })
                    .catch(function () { b.disabled = false; b.textContent = '삭제'; });
                return;
            }
            // 전역 재캐싱 (파일 없이 thread_id 해제)
            var rc = e.target.closest && e.target.closest('.law-list-recache');
            if (rc) {
                rc.disabled = true; rc.textContent = '처리 중…';
                fetch('/upload-cache/recache', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ law_name: rc.dataset.law }),
                })
                    .then(function () { loadUploadCache(ov); })
                    .catch(function () { rc.disabled = false; rc.textContent = '전역 재캐싱'; });
                return;
            }
            // 교체 (파일 선택 → 삭제 후 재업로드)
            var rp = e.target.closest && e.target.closest('.law-list-replace');
            if (rp) {
                var inp = ov.querySelector('#upload-replace-input');
                inp.dataset.oldLaw = rp.dataset.law;
                inp.click();
                return;
            }
        });
        // 파일 추가: 선택 즉시 업로드 (같은 파일 재선택 위해 value 초기화)
        ov.querySelector('#upload-add-input').addEventListener('change', function (e) {
            var file = e.target.files && e.target.files[0];
            uploadCacheFile(ov, file);
            e.target.value = '';
        });
        // 교체: 기존 항목 삭제 후 새 파일 등록
        ov.querySelector('#upload-replace-input').addEventListener('change', function (e) {
            var file = e.target.files && e.target.files[0];
            var oldLaw = e.target.dataset.oldLaw;
            e.target.value = '';
            if (!file || !oldLaw) return;
            var status = ov.querySelector('#upload-add-status');
            if (!/\.pdf$/i.test(file.name)) { status.textContent = 'PDF 파일만 가능합니다.'; return; }
            status.textContent = '⏳ 교체 중… (' + file.name + ')';
            fetch('/upload-cache/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ law_name: oldLaw }),
            })
                .then(function () {
                    var fd = new FormData(); fd.append('file', file);
                    return fetch('/upload-cache/add', { method: 'POST', body: fd });
                })
                .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
                .then(function (res) {
                    if (!res.ok || res.d.error) { status.textContent = '✗ ' + (res.d.error || '교체 실패'); return; }
                    status.textContent = '✓ 「' + res.d.law_name + '」(으)로 교체됨 (' + res.d.chunks + '개 청크)';
                    loadUploadCache(ov);
                })
                .catch(function () { status.textContent = '✗ 교체 실패 (네트워크)'; });
        });
        ov.querySelector('.law-list-close').onclick = function () { ov.style.display = 'none'; };
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { var m = document.getElementById('upload-cache-modal'); if (m) m.style.display = 'none'; }
        });
        document.body.appendChild(ov);
        loadUploadCache(ov);
    }

    // ── 대화 저장: 현재 화면의 질문·답변을 마크다운 파일로 다운로드 ──────
    function downloadChat() {
        var steps = Array.prototype.slice.call(document.querySelectorAll(
            '[data-step-type="user_message"], [data-step-type="assistant_message"]'));
        if (!steps.length) {   // 셀렉터 변동 대비 폴백
            steps = Array.prototype.slice.call(document.querySelectorAll('[data-testid="step"]'));
        }
        var lines = [];
        steps.forEach(function (el) {
            var t = (el.innerText || '').trim();
            if (!t) return;
            var isUser = el.getAttribute('data-step-type') === 'user_message';
            lines.push((isUser ? '## 질문' : '## 답변') + '\n\n' + t);
        });
        if (!lines.length) { alert('저장할 대화가 없습니다.'); return; }
        var now = new Date();
        function p(n) { return (n < 10 ? '0' : '') + n; }
        var stamp = now.getFullYear() + p(now.getMonth() + 1) + p(now.getDate())
            + '_' + p(now.getHours()) + p(now.getMinutes());
        var head = '# 법령 Q&A 대화 (' + now.toLocaleString('ko-KR') + ')\n\n';
        var blob = new Blob([head + lines.join('\n\n---\n\n') + '\n'],
            { type: 'text/markdown;charset=utf-8' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'LawQNA_대화_' + stamp + '.md';
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }

    // ── 모델 선택 드롭다운 — 질문 시 묻지 않고 헤더에서 선택 ──────────
    // 새 모델(예: ChatGPT)은 이 배열에 항목만 추가하면 된다 (백엔드 /provider
    // 허용 목록과 06_Generator provider 분기도 함께 확장).
    var MODELS = [
        { id: 'gemini', label: '⚡ Gemini' },
        { id: 'claude', label: '🔷 Claude' }
    ];
    var MODEL_KEY = 'model_provider';

    function currentModel() {
        var v = '';
        try { v = localStorage.getItem(MODEL_KEY) || ''; } catch (e) { }
        return MODELS.some(function (m) { return m.id === v; }) ? v : MODELS[0].id;
    }

    function modelLabel(id) {
        var m = MODELS.find(function (x) { return x.id === id; });
        return m ? m.label : MODELS[0].label;
    }

    function renderModelButton() {
        var btn = document.getElementById('model-select-btn');
        if (!btn) return;
        btn.textContent = modelLabel(currentModel()) + ' ▾';
        btn.title = '답변 모델 선택';
    }

    function pushModel(p) {
        try {
            fetch('/provider', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ provider: p })
            });
        } catch (e) { }
    }

    function closeModelMenu() {
        var m = document.getElementById('model-select-menu');
        if (m) m.remove();
        document.removeEventListener('click', closeModelMenu);
    }

    function chooseModel(id) {
        try { localStorage.setItem(MODEL_KEY, id); } catch (e) { }
        renderModelButton();
        pushModel(id);
        closeModelMenu();
    }

    function toggleModelMenu(ev) {
        ev.stopPropagation();
        if (document.getElementById('model-select-menu')) { closeModelMenu(); return; }
        var btn = document.getElementById('model-select-btn');
        if (!btn) return;
        var r = btn.getBoundingClientRect();
        var menu = document.createElement('div');
        menu.id = 'model-select-menu';
        menu.className = 'model-menu';
        menu.style.top = (r.bottom + 6) + 'px';
        menu.style.left = r.left + 'px';
        var cur = currentModel();
        MODELS.forEach(function (m) {
            var it = document.createElement('button');
            it.type = 'button';
            it.className = 'model-menu-item' + (m.id === cur ? ' active' : '');
            it.textContent = m.label + (m.id === cur ? '  ✓' : '');
            it.onclick = function (e) { e.stopPropagation(); chooseModel(m.id); };
            menu.appendChild(it);
        });
        document.body.appendChild(menu);
        setTimeout(function () { document.addEventListener('click', closeModelMenu); }, 0);
    }

    var modelSynced = false;
    function syncModelOnce() {
        // 서버 재시작으로 선호가 비워져도 페이지 로드 시 로컬 선택을 재동기화
        if (modelSynced) return;
        modelSynced = true;
        pushModel(currentModel());
    }

    // ── 다크모드 제거: 테마 토글 숨김 + 라이트 강제 ──────────────────
    function killDarkMode() {
        try {
            var root = document.documentElement;
            if (root.classList.contains('dark')) {
                root.classList.remove('dark');
                try { localStorage.setItem('vite-ui-theme', 'light'); } catch (e) { }
                try { localStorage.setItem('theme', 'light'); } catch (e) { }
            }
            var tt = document.getElementById('theme-toggle');
            if (tt) tt.style.display = 'none';
            // lucide 아이콘 클래스 변주까지 부분일치로 — 해/달 아이콘 품은 버튼 숨김
            document.querySelectorAll(
                'svg[class*="-sun"], svg[class*="-moon"], svg[class*="Sun"], svg[class*="Moon"]')
                .forEach(function (s) {
                    var b = s.closest('button');
                    if (b && b.id !== 'model-select-btn') b.style.display = 'none';
                });
        } catch (e) { }
    }

    // ── 오른쪽 고정 바: 상단 헤더에 있던 액션 버튼들을 이리로 이동 ──────────
    function ensureRightBar() {
        var bar = document.getElementById('usun-right-bar');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'usun-right-bar';
            var title = document.createElement('div');
            title.className = 'usun-rb-title';
            title.textContent = '도구';
            bar.appendChild(title);
            document.body.appendChild(bar);
        }
        return bar;
    }

    // 기준점으로만 쓰던 'Readme' 링크는 이제 불필요 — 보이면 숨긴다
    function hideReadme() {
        try {
            var readme = Array.prototype.slice.call(document.querySelectorAll('button, a'))
                .find(function (el) { return el.textContent.trim() === 'Readme'; });
            if (readme) readme.style.display = 'none';
        } catch (e) { }
    }

    function insertRightBarButtons() {
        try {
            var bar = ensureRightBar();
            if (document.getElementById('law-list-btn')
                && document.getElementById('upload-cache-btn')
                && document.getElementById('chat-save-btn')
                && document.getElementById('model-select-btn')) {
                renderModelButton();   // 라벨만 최신화
                return;
            }
            function mk(id, text, handler) {
                if (document.getElementById(id)) return;
                var b = document.createElement('button');
                b.id = id;
                b.type = 'button';
                b.className = 'law-list-btn';
                if (text) b.textContent = text;
                b.onclick = handler;
                bar.appendChild(b);
            }
            mk('law-list-btn', '내장 법령 목록', showLawListModal);
            mk('upload-cache-btn', '조례 라이브러리', showUploadModal);
            mk('chat-save-btn', '대화 저장', downloadChat);
            mk('model-select-btn', '', toggleModelMenu);   // 라벨은 renderModelButton이 채움
            renderModelButton();
            syncModelOnce();
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
        loadStartersMeta();
        insertRightBarButtons();
        hideReadme();
        if (hasMessages()) {
            removeLogo();
            removeStarterGrid();
        } else {
            try { layoutStarterGrid(); } catch (e) { }   // 실패해도 로고·바는 살림
            insertLogo();
        }
        insertSidebarResizeHandle();
        killDarkMode();
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();

