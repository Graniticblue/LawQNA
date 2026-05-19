(function () {
    // ── 헤더 고정 법령 목록 버튼 ─────────────────────────────
    const nativeValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
    )?.set;

    function insertHeaderBtn() {
        if (document.getElementById('header-law-btn')) return;

        const btn = document.createElement('button');
        btn.id = 'header-law-btn';
        btn.textContent = '📋 지원 법령';
        btn.type = 'button';
        btn.style.cssText = [
            'position:fixed', 'top:10px', 'right:16px', 'z-index:9999',
            'padding:5px 14px', 'border-radius:6px',
            'border:1.5px solid #1565C0', 'background:white',
            'color:#1565C0', 'font-size:13px', 'font-weight:500',
            'cursor:pointer', 'transition:all 0.15s',
            'box-shadow:0 1px 4px rgba(0,0,0,0.08)',
        ].join(';');
        btn.addEventListener('mouseenter', () => { btn.style.background='#1565C0'; btn.style.color='white'; });
        btn.addEventListener('mouseleave', () => { btn.style.background='white'; btn.style.color='#1565C0'; });
        btn.addEventListener('click', () => {
            const ta = document.querySelector('textarea');
            const submit = document.getElementById('chat-submit');
            if (!ta || !submit || !nativeValueSetter) return;
            nativeValueSetter.call(ta, '📋 내장 법령 목록');
            ta.dispatchEvent(new Event('input', { bubbles: true }));
            setTimeout(() => submit.click(), 50);
        });
        document.body.appendChild(btn);
    }

    const headerObserver = new MutationObserver(insertHeaderBtn);
    headerObserver.observe(document.documentElement, { childList: true, subtree: true });
    insertHeaderBtn();

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

    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();
