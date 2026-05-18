(function () {
    // ── 카테고리 칩 ─────────────────────────────────────────
    const CHIPS_ID = 'category-chips';
    const CATEGORIES = [
        { label: '#허가·신고',  text: '건축허가와 건축신고의 대상 기준과 차이를 알려주세요.' },
        { label: '#용도지역',   text: '용도지역별 건폐율·용적률 기준과 건축 제한을 알려주세요.' },
        { label: '#피난·방화',  text: '피난계단 및 방화구획 설치 기준을 알려주세요.' },
        { label: '#감리',       text: '건축 감리 대상 건축물과 감리 절차를 알려주세요.' },
        { label: '#구조안전',   text: '내진설계 대상 및 구조 안전 확인 기준을 알려주세요.' },
    ];
    const nativeValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
    )?.set;

    function insertChips(inputBox) {
        if (document.getElementById(CHIPS_ID)) return;
        const wrap = document.createElement('div');
        wrap.id = CHIPS_ID;
        wrap.style.cssText = [
            'display:flex', 'flex-wrap:wrap', 'gap:6px',
            'max-width:' + inputBox.getBoundingClientRect().width + 'px',
            'margin:0 auto 8px auto',
        ].join(';');
        CATEGORIES.forEach(cat => {
            const btn = document.createElement('button');
            btn.textContent = cat.label;
            btn.type = 'button';
            btn.style.cssText = [
                'padding:3px 12px', 'border-radius:9999px',
                'border:1px solid #1565C0', 'background:white',
                'color:#1565C0', 'font-size:12px', 'cursor:pointer',
                'transition:all 0.15s',
            ].join(';');
            btn.addEventListener('mouseenter', () => { btn.style.background='#1565C0'; btn.style.color='white'; });
            btn.addEventListener('mouseleave', () => { btn.style.background='white'; btn.style.color='#1565C0'; });
            btn.addEventListener('click', () => {
                const ta = document.querySelector('textarea');
                if (!ta || !nativeValueSetter) return;
                nativeValueSetter.call(ta, cat.text);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.focus();
            });
            wrap.appendChild(btn);
        });
        inputBox.parentNode.insertBefore(wrap, inputBox);
    }

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

    function update() {
        const submitBtn = document.getElementById('chat-submit');
        const inputBox = submitBtn?.parentElement?.parentElement?.parentElement;

        if (hasMessages()) {
            removeLogo();
        } else {
            insertLogo();
        }

        if (inputBox) {
            insertChips(inputBox);
        }
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();
