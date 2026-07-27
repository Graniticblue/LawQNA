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
        // 구버전(#usun-logo-wrap) 로고 잔재 정리용 — 현재 로고는 웰컴 오버레이 안에서 렌더
        const wrap = document.getElementById(LOGO_WRAP_ID);
        if (wrap) wrap.remove();
    }

    // ── 추천질문 → 웰컴 카드 (6개, 1/1/2/2 고정크기 그리드, 화면 중앙) ──────────
    // 지난 실패 교훈: ①React 트리에 노드 삽입/컨테이너 숨김 → 재조정 크래시(백지)
    //               ②매 update마다 DOM 텍스트 재설정 → MutationObserver 무한루프
    // 그래서: 카드 그리드는 body에 fixed 오버레이(=React 밖, 크래시 안전)로 그리고,
    // 네이티브 스타터는 '개별 버튼만' 숨긴다(컨테이너·형제 불건드림). 카드 클릭은
    // 숨긴 네이티브 버튼의 .click()에 위임(전송 동작 유지). 컴포저는 하단 고정.
    // 유지작업은 signature/멱등이라 옵저버 루프 없음. 유형값은 /starters-meta.
    var _startersMeta = null, _metaFetched = false;
    function loadStartersMeta() {
        if (_metaFetched) return;
        _metaFetched = true;
        fetch('/starters-meta')
            .then(function (r) { return r.json(); })
            .then(function (m) {
                _startersMeta = m || {};
                var ov = document.getElementById('usun-welcome-cards');
                if (ov) ov.remove();   // 메타 도착 → 유형 딱지·상세 질의 포함해 재빌드
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

    function pinComposer(on) {
        var s = document.getElementById('chat-submit');
        var box = s && s.parentElement && s.parentElement.parentElement
            && s.parentElement.parentElement.parentElement;
        if (!box) return;
        if (on) box.classList.add('usun-welcome-input');
        else box.classList.remove('usun-welcome-input');
    }

    function teardownWelcomeCards() {
        var ov = document.getElementById('usun-welcome-cards');
        if (ov) ov.remove();
        nativeStarterButtons().forEach(function (b) { b.classList.remove('usun-starter-hidden'); });
        pinComposer(false);
    }

    function buildWelcomeCards() {
        var nat = nativeStarterButtons();
        if (nat.length < 1) return;
        var labels = nat.map(starterLabel);
        var sig = labels.join('|');
        var ov = document.getElementById('usun-welcome-cards');
        if (!(ov && ov.dataset.sig === sig)) {   // 구성이 바뀔 때만 재빌드(멱등 → 루프 없음)
            if (ov) ov.remove();
            var meta = _startersMeta || {};
            ov = document.createElement('div');
            ov.id = 'usun-welcome-cards';
            ov.dataset.sig = sig;
            // 그룹 상단: 회사 로고 (오버레이 안에 함께 두어 카드와 한 묶음으로 중앙 정렬)
            var logo = document.createElement('img');
            logo.className = 'usun-wc-logo';
            logo.src = 'https://www.usun.co.kr/assets/images/logo.png';
            logo.alt = 'usun';
            ov.appendChild(logo);
            // 그 아래: 카드 그리드
            var grid = document.createElement('div');
            grid.className = 'usun-wc-grid';
            labels.forEach(function (label) {
                var info = meta[label] || {};
                var t = info.type || '';
                var msg = info.message || '';
                var card = document.createElement('button');
                card.type = 'button';
                card.className = 'usun-wc-card';
                if (t) {
                    var chip = document.createElement('span');
                    chip.className = 'usun-wc-chip';
                    chip.setAttribute('data-usun-type', t);
                    chip.textContent = t;
                    card.appendChild(chip);
                }
                var title = document.createElement('span');
                title.className = 'usun-wc-title';
                title.textContent = label;
                card.appendChild(title);
                if (msg) {
                    var desc = document.createElement('span');
                    desc.className = 'usun-wc-desc';
                    desc.textContent = msg;   // 클릭 시 입력될 실제 질의문
                    card.appendChild(desc);
                }
                card.addEventListener('click', function () {
                    var tgt = nativeStarterButtons().filter(function (b) {
                        return starterLabel(b) === label;
                    })[0];
                    if (tgt) tgt.click();   // 전송은 chainlit 네이티브 핸들러에 위임
                });
                grid.appendChild(card);
            });
            ov.appendChild(grid);
            document.body.appendChild(ov);   // body = React 트리 밖 → 크래시 안전
        }
        // 네이티브 스타터는 개별 버튼만 숨김(컨테이너·형제 불건드림) + 컴포저 하단 고정
        nat.forEach(function (b) { b.classList.add('usun-starter-hidden'); });
        pinComposer(true);
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

    // ── 대화 TXT 저장 (마크다운 기호 없이 플레인) ─────────────────────
    function downloadChatTxt() {
        var steps = Array.prototype.slice.call(document.querySelectorAll(
            '[data-step-type="user_message"], [data-step-type="assistant_message"]'));
        if (!steps.length) steps = Array.prototype.slice.call(document.querySelectorAll('[data-testid="step"]'));
        var lines = [];
        steps.forEach(function (el) {
            var t = (el.innerText || '').trim();
            if (!t) return;
            var isUser = el.getAttribute('data-step-type') === 'user_message';
            lines.push((isUser ? '[질문]' : '[답변]') + '\n' + t);
        });
        if (!lines.length) { alert('저장할 대화가 없습니다.'); return; }
        var now = new Date();
        function p(n) { return (n < 10 ? '0' : '') + n; }
        var stamp = now.getFullYear() + p(now.getMonth() + 1) + p(now.getDate())
            + '_' + p(now.getHours()) + p(now.getMinutes());
        var head = '법령 Q&A 대화 (' + now.toLocaleString('ko-KR') + ')\n\n';
        var blob = new Blob([head + lines.join('\n\n------------------------------\n\n') + '\n'],
            { type: 'text/plain;charset=utf-8' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'LawQNA_대화_' + stamp + '.txt';
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }

    // ── PDF 내보내기 — 브라우저 인쇄창(→'PDF로 저장'). @media print에서 크롬 숨김 ──
    function exportPdf() {
        var steps = document.querySelectorAll('[data-step-type="user_message"], [data-step-type="assistant_message"]');
        if (!steps.length) { alert('내보낼 대화가 없습니다.'); return; }
        window.print();
    }

    // ── 새 대화 — chainlit 네이티브 새 채팅 버튼을 누르고, 없으면 앱 루트로 이동 ──
    function newChat() {
        try {
            var btn = Array.prototype.slice.call(document.querySelectorAll('button, a')).find(function (el) {
                var al = el.getAttribute('aria-label') || '';
                var id = (el.id || '').toLowerCase();
                return id.indexOf('new-chat') !== -1
                    || /new chat|new conversation/i.test(al)
                    || /새\s*(채팅|대화)/.test(al);
            });
            if (btn) { btn.click(); return; }
        } catch (e) { }
        window.location.assign(window.location.origin + window.location.pathname);
    }

    // ── 마지막 사용자 질문 텍스트 ────────────────────────────────────
    function lastUserQuestion() {
        var us = Array.prototype.slice.call(document.querySelectorAll('[data-step-type="user_message"]'));
        return us.length ? (us[us.length - 1].innerText || '').trim() : '';
    }

    // ── 입력창에 텍스트 주입 후 전송 (React 제어 textarea) ────────────
    function sendPrompt(text) {
        var s = document.getElementById('chat-submit');
        var box = s && s.parentElement && s.parentElement.parentElement
            && s.parentElement.parentElement.parentElement;
        var ta = box && box.querySelector('textarea');
        if (!ta || !s) { alert('입력창을 찾지 못했습니다.'); return false; }
        var d = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
        if (d && d.set) d.set.call(ta, text); else ta.value = text;
        ta.dispatchEvent(new Event('input', { bubbles: true }));   // React 상태 반영
        setTimeout(function () { s.click(); }, 40);
        return true;
    }

    // 답변 재생성 — 직전 질문을 그대로 재전송
    function regenerateAnswer() {
        var q = lastUserQuestion();
        if (!q) { alert('재생성할 이전 질문이 없습니다.'); return; }
        sendPrompt(q);
    }

    // 근거 더 찾기 — 직전 질문에 근거 보강 요청을 덧붙여 재전송
    function findMoreEvidence() {
        var q = lastUserQuestion();
        if (!q) { alert('먼저 질문을 해주세요.'); return; }
        sendPrompt(q + '\n\n(위 질문에 대해 관련 조문·법제처 해석례·판례 근거를 더 폭넓게 찾아 다시 답변해줘.)');
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
        // 동일값이면 DOM을 건드리지 않는다 — 매 mutation마다 textContent를 재설정하면
        // 그 자체가 childList 변경이라 MutationObserver→update→재설정 무한루프가 된다.
        var txt = modelLabel(currentModel()) + ' ▾';
        if (btn.textContent !== txt) btn.textContent = txt;
        if (btn.title !== '답변 모델 선택') btn.title = '답변 모델 선택';
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

    // ── 모니터링 패널: 이 대화에서 참조한 법령/해석례/판례 누적 표시 ──────────
    // /monitor(서버 세션 누적본)를 주기적으로 받아 우측 바에 렌더한다.
    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function _monGroup(title, items) {
        if (!items || !items.length) return '';
        var lis = items.map(function (it) {
            var n = (it.n > 1) ? ' <span class="usun-mon-n">×' + it.n + '</span>' : '';
            return '<li>' + _esc(it.label) + n + '</li>';
        }).join('');
        return '<div class="usun-mon-grp"><div class="usun-mon-h">' + title
            + ' <span class="usun-mon-c">' + items.length + '</span></div><ul>' + lis + '</ul></div>';
    }
    function refreshMonitor() {
        var box = document.getElementById('usun-monitor');
        if (!box) return;
        fetch('/monitor', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var total = (d.law || []).length + (d.interp || []).length + (d.case || []).length;
                if (!total) {
                    box.innerHTML = '<div class="usun-mon-empty">아직 참조된 자료가 없습니다.<br>'
                        + '질문하면 이 대화에서 참고한 법령·해석례·판례가 쌓입니다.</div>';
                    return;
                }
                box.innerHTML = _monGroup('법령', d.law)
                    + _monGroup('해석례', d.interp)
                    + _monGroup('판례', d.case);
            })
            .catch(function () { /* 네트워크 실패는 다음 주기에 재시도 */ });
    }

    // 모니터링 수동추가 — 모달 결과창에 법령/조례 검색 결과 렌더 (추가는 클릭 위임)
    function doLawSearch(q) {
        var box = document.getElementById('law-search-results');
        if (!box) return;
        q = (q || '').trim();
        if (q.length < 2) { box.innerHTML = '<div class="usun-law-hint">2글자 이상 입력하세요</div>'; return; }
        box.innerHTML = '<div class="usun-law-hint">검색 중…</div>';
        fetch('/law-search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var rs = (d && d.results) || [];
                if (!rs.length) { box.innerHTML = '<div class="usun-law-hint">결과 없음</div>'; return; }
                box.innerHTML = rs.map(function (it) {
                    var k = (it.kind === '조례') ? 'ord' : 'law';
                    return '<div class="usun-law-item" data-kind="' + _esc(it.kind) + '" data-name="' + _esc(it.name) + '">'
                        + '<span class="usun-law-kind usun-law-kind-' + k + '">' + _esc(it.kind) + '</span>'
                        + '<span class="usun-law-nm">' + _esc(it.name) + '</span>'
                        + '<button type="button" class="usun-law-add">추가</button></div>';
                }).join('');
            })
            .catch(function () { box.innerHTML = '<div class="usun-law-hint">검색 실패</div>'; });
    }

    // 법령·조례 검색·추가 모달 (우측 바 버튼 → 새 창). 내장 법령 목록 모달과 같은 껍데기 사용.
    function showLawSearchModal() {
        var ov = document.getElementById('law-search-modal');
        if (ov) {
            ov.style.display = 'flex';
            var q0 = ov.querySelector('#law-search-q');
            if (q0) setTimeout(function () { q0.focus(); }, 30);
            return;
        }
        ov = document.createElement('div');
        ov.id = 'law-search-modal';
        ov.innerHTML =
            '<div class="law-list-box">' +
            '<button class="law-list-close" aria-label="닫기">✕</button>' +
            '<h2 style="font-size:18px;margin:0 0 4px">법령·조례 검색·추가</h2>' +
            '<div class="law-db-foot" style="margin:0 0 14px">법제처 API에서 검색해 캐싱·적재합니다. 추가한 자료는 모니터링(앞으로 참고할 자료)에 등재됩니다.</div>' +
            '<div class="law-search-bar">' +
            '<input type="text" id="law-search-q" placeholder="법령·조례명을 입력하세요 (2글자 이상)" />' +
            '<button type="button" id="law-search-go">🔎 검색</button>' +
            '</div>' +
            '<div id="law-search-results" class="law-search-results"></div>' +
            '</div>';
        ov.addEventListener('click', function (e) { if (e.target === ov) ov.style.display = 'none'; });
        ov.querySelector('.law-list-close').onclick = function () { ov.style.display = 'none'; };
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { var m = document.getElementById('law-search-modal'); if (m) m.style.display = 'none'; }
        });
        var qin = ov.querySelector('#law-search-q');
        var qgo = ov.querySelector('#law-search-go');
        var res = ov.querySelector('#law-search-results');
        qgo.addEventListener('click', function () { doLawSearch(qin.value); });
        qin.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); doLawSearch(qin.value); }
        });
        // 백스페이스 등으로 입력을 비우면 결과도 지운다
        qin.addEventListener('input', function () { if (!qin.value.trim()) res.innerHTML = ''; });
        res.addEventListener('click', function (e) {
            var b = e.target.closest && e.target.closest('.usun-law-add');
            if (!b) return;
            var item = b.closest('.usun-law-item');
            if (!item) return;
            b.disabled = true; b.textContent = '…';
            fetch('/law-add', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    kind: item.getAttribute('data-kind'),
                    name: item.getAttribute('data-name'),
                }),
            })
                .then(function (r) { return r.json(); })
                .then(function (res2) {
                    b.textContent = (res2 && !res2.error) ? '✓ 추가됨' : '✗';
                    if (res2 && !res2.error) { item.classList.add('added'); refreshMonitor(); }
                })
                .catch(function () { b.textContent = '✗'; });
        });
        document.body.appendChild(ov);
        ov.style.display = 'flex';
        setTimeout(function () { qin.focus(); }, 30);
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

    // 기준점으로만 쓰던 'Readme' 링크는 이제 불필요 — 보이면 숨긴다.
    // 한 번 숨기면 종료(매 mutation마다 전체 DOM 스캔하지 않도록).
    var _readmeHidden = false;
    function hideReadme() {
        if (_readmeHidden) return;
        try {
            var readme = Array.prototype.slice.call(document.querySelectorAll('button, a'))
                .find(function (el) { return el.textContent.trim() === 'Readme'; });
            if (readme) { readme.style.display = 'none'; _readmeHidden = true; }
        } catch (e) { }
    }

    function insertRightBarButtons() {
        try {
            var bar = ensureRightBar();
            if (bar.dataset.built === '1') return;   // 1회만 구성(매 mutation마다 호출되므로)
            function sec(text) {
                var h = document.createElement('div');
                h.className = 'usun-rb-sec';
                h.textContent = text;
                bar.appendChild(h);
            }
            function mk(id, text, handler) {
                var b = document.createElement('button');
                b.id = id;
                b.type = 'button';
                b.className = 'law-list-btn';
                if (text) b.textContent = text;
                b.onclick = handler;
                bar.appendChild(b);
            }
            sec('세션');
            mk('new-chat-btn', '✏️ 새 대화', newChat);
            sec('내보내기');
            mk('export-md-btn', '📝 마크다운', downloadChat);
            mk('export-pdf-btn', '📕 PDF', exportPdf);
            mk('export-txt-btn', '📄 TXT', downloadChatTxt);
            sec('답변');
            mk('evidence-btn', '🔎 근거 더 찾기', findMoreEvidence);
            mk('regen-btn', '♻️ 답변 재생성', regenerateAnswer);
            sec('자료');
            mk('law-list-btn', '📚 내장 법령 목록', showLawListModal);
            mk('upload-cache-btn', '🗂️ 조례 라이브러리', showUploadModal);
            sec('모델');
            mk('model-select-btn', '', toggleModelMenu);   // 라벨은 renderModelButton이 채움
            renderModelButton();
            syncModelOnce();
            sec('모니터링');
            mk('law-search-btn', '🔎 법령·조례 검색·추가', showLawSearchModal);   // 클릭 → 모달
            // 누적 현황
            var mon = document.createElement('div');
            mon.id = 'usun-monitor';
            mon.className = 'usun-monitor';
            bar.appendChild(mon);
            refreshMonitor();   // 초기 1회 (이후 주기 폴링)
            bar.dataset.built = '1';
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
            removeLogo();   // 혹시 남은 구버전 로고(#usun-logo-wrap) 정리
            teardownWelcomeCards();
        } else {
            try { buildWelcomeCards(); } catch (e) { }   // 로고+카드 묶음(오버레이) 렌더
        }
        insertSidebarResizeHandle();
        killDarkMode();
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    // 모니터링 패널 주기 갱신 — 서버 세션 누적본을 4초마다 반영(작은 GET)
    setInterval(function () {
        if (document.getElementById('usun-monitor')) refreshMonitor();
    }, 4000);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();

