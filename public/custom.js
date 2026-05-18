(function () {
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
