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
        img.alt = '유선건축사사무소';
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

    function findReadmeControl() {
        // 'Readme' 텍스트를 가진 모든 요소 중 가장 바깥(클릭 컨트롤) 선택.
        var els = Array.prototype.slice.call(
            document.querySelectorAll('button, a, div, span, [role="button"]'));
        var matches = els.filter(function (e) { return e.textContent && e.textContent.trim() === 'Readme'; });
        if (!matches.length) return null;
        return matches.reduce(function (a, b) { return a.contains(b) ? a : b; });
    }

    function insertLawListButton() {
        try {
            if (document.getElementById('law-list-btn')) return;
            var btn = document.createElement('button');
            btn.id = 'law-list-btn';
            btn.type = 'button';
            btn.textContent = '📋 내장 법령 목록';
            btn.className = 'law-list-btn';
            btn.onclick = showLawListModal;
            var ctrl = findReadmeControl();
            if (ctrl && ctrl.parentElement) {
                ctrl.parentElement.insertBefore(btn, ctrl);
            } else {
                btn.classList.add('law-list-btn-float');  // Readme 못 찾으면 우상단 고정 폴백
                document.body.appendChild(btn);
            }
        } catch (e) { /* DOM 변동 중 실패는 무시(다음 mutation에 재시도) */ }
    }

    function update() {
        if (hasMessages()) {
            removeLogo();
        } else {
            insertLogo();
        }
        layoutStarters();
        insertLawListButton();
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();
