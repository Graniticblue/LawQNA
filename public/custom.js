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

    function update() {
        if (hasMessages()) {
            removeLogo();
        } else {
            insertLogo();
        }
        layoutStarters();
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();
