(function () {
    function insertLogo() {
        if (document.getElementById('usun-logo')) return;

        const submitBtn = document.getElementById('chat-submit');
        if (!submitBtn) return;

        // #chat-submit 기준으로 3단계 위 = 둥근 입력박스 컨테이너
        const inputBox = submitBtn.parentElement?.parentElement?.parentElement;
        if (!inputBox || !inputBox.parentNode) return;

        const wrap = document.createElement('div');
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
        img.style.cssText = [
            'max-height: 52px',
            'max-width: 200px',
            'object-fit: contain',
        ].join(';');

        wrap.appendChild(img);
        inputBox.parentNode.insertBefore(wrap, inputBox);
    }

    const observer = new MutationObserver(insertLogo);
    observer.observe(document.documentElement, { childList: true, subtree: true });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', insertLogo);
    } else {
        insertLogo();
    }
})();
