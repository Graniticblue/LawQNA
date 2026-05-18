(function () {
    function insertLogo() {
        if (document.getElementById('usun-logo')) return;

        const submitBtn = document.getElementById('chat-submit');
        if (!submitBtn) return;

        // 입력창 최상위 컨테이너까지 올라가기
        let container = submitBtn.closest('form');
        if (!container) {
            let el = submitBtn;
            for (let i = 0; i < 6; i++) {
                el = el.parentElement;
                if (!el) break;
                container = el;
            }
        }
        if (!container || !container.parentNode) return;

        const img = document.createElement('img');
        img.id = 'usun-logo';
        img.src = 'https://www.usun.co.kr/assets/images/logo.png';
        img.alt = '유선건축사사무소';
        img.style.cssText = [
            'display: block',
            'margin: 0 auto 14px auto',
            'max-height: 56px',
            'max-width: 220px',
            'object-fit: contain',
            'opacity: 0.92',
        ].join(';');

        container.parentNode.insertBefore(img, container);
    }

    const observer = new MutationObserver(insertLogo);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', insertLogo);
    } else {
        insertLogo();
    }
})();
