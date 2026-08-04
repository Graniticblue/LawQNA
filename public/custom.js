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

    // 스타터 라벨 선두의 장식 이모지만 제거(표시 전용). 원본 라벨은 /starters-meta 조회 키라
    // 그대로 두고, 화면에 뿌릴 때만 벗긴다. 서러게이트쌍 + 기호/화살표 BMP 대역 + 변이선택자·ZWJ.
    // ①②③(U+2460-24FF)은 대역에서 제외 — 다른 UI 문구가 쓰는 글자라 같이 지워지면 안 된다.
    var _LEAD_EMOJI = /^(?:[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2190-\u21FF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF]|[\uFE0E\uFE0F\u200D\u20E3])+\s*/;
    function plainStarterLabel(label) {
        return ((label || '').replace(_LEAD_EMOJI, '').trim()) || label;
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

    // ══ 웰컴(초기창) 유틸 — SCREEN 1 레퍼런스: 입력창이 주인공 ══════════════
    function _el(tag, cls, txt) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (txt != null) e.textContent = txt;
        return e;
    }
    function _autoGrow() { this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 160) + 'px'; }
    function modelPlainLabel(id) { return id === 'claude' ? 'Claude' : 'Gemini'; }

    // 히어로 입력 → 전송(화면 밖에 숨긴 실제 컴포저로 sendPrompt 위임)
    function heroSend(ta) {
        var v = (ta.value || '').trim();
        if (!v) { ta.focus(); return; }
        sendPrompt(v);
    }

    // 참고자료 등록 섹션 접힘 상태(localStorage 기억). 기본값=접힘(명시적 '0'일 때만 펼침).
    var SCOPE_COLLAPSE_KEY = 'usun_scope_collapsed';
    function scopeCollapsed() { try { return localStorage.getItem(SCOPE_COLLAPSE_KEY) !== '0'; } catch (e) { return true; } }
    function setScopeCollapsed(on) { try { localStorage.setItem(SCOPE_COLLAPSE_KEY, on ? '1' : '0'); } catch (e) { } }

    // 예시 질문 섹션 접힘 상태(localStorage 기억). 기본값=펼침(명시적 '1'일 때만 접힘).
    var EX_COLLAPSE_KEY = 'usun_ex_collapsed';
    function exCollapsed() { try { return localStorage.getItem(EX_COLLAPSE_KEY) === '1'; } catch (e) { return false; } }
    function setExCollapsed(on) { try { localStorage.setItem(EX_COLLAPSE_KEY, on ? '1' : '0'); } catch (e) { } }

    // 검색 범위 카드 1장 (법령 / 우리 지역 조례 / 내 문서) — 카드 전체가 진입점(클릭·Enter).
    // 법령=법령만 검색(조례는 지역 카드로 분리). onBody = 카드 클릭 시 열 모달.
    function scopeCard(kind) {
        var conf = {
            law: {
                num: 1, t: '법령', bodyId: 'usun-scope-law-body', body: '전체 법령에서 검색',
                hint: '필요한 법령을 추가하면 우선 근거로 반영합니다.',
                onBody: showLawSearchModal, act: '＋ 법령 추가'
            },
            region: {
                num: 2, t: '우리 지역 조례', bodyId: 'usun-scope-region-body', body: '전국 공통 범위',
                hint: '지역을 선택하면 그 지자체 조례를 등록할 수 있습니다.',
                onBody: showRegionModal, act: '지역 선택'
            },
            doc: {
                num: 3, t: '내 문서', bodyId: '', body: '없음',
                hint: '지구단위계획·운영기준을 올리면 그 내용까지 인용합니다.',
                onBody: showUploadModal, act: '문서 올리기'
            }
        }[kind];
        var c = _el('div', 'usun-scope-card usun-scope-' + kind);
        c.setAttribute('role', 'button');
        c.setAttribute('tabindex', '0');
        c.innerHTML =
            '<div class="usun-scope-cardt"><span class="usun-scope-num">' + conf.num + '</span>' + _esc(conf.t) + '</div>'
            + '<div class="usun-scope-val muted"' + (conf.bodyId ? (' id="' + conf.bodyId + '"') : '') + '>' + _esc(conf.body) + '</div>'
            + '<div class="usun-scope-hint2">' + _esc(conf.hint) + '</div>'
            + '<div class="usun-scope-acts"><span class="usun-scope-act">' + _esc(conf.act) + '</span></div>';
        function open() { try { conf.onBody(); } catch (err) { } }
        c.addEventListener('click', open);   // 카드 전체(본문·라벨 포함) 클릭으로 열림
        c.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        });
        return c;
    }

    // 자료 캐싱(law-add) 진행 추적 — 모달을 닫아도 카드에 유지. 조례=②지역카드, 법령=①법령카드.
    var _pendingCache = 0;    // 법령
    var _pendingRegion = 0;   // 조례(지역)
    function cacheLaw(kind, name) {
        var isOrd = (kind === '조례');
        if (isOrd) _pendingRegion++; else _pendingCache++;
        refreshWelcomeScope();
        return fetch('/law-add', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kind: kind, name: name }),
        })
            .then(function (r) { return r.json(); })
            .catch(function () { return { error: 'net' }; })
            .then(function (res) {
                if (isOrd) _pendingRegion = Math.max(0, _pendingRegion - 1);
                else _pendingCache = Math.max(0, _pendingCache - 1);
                refreshMonitor(); refreshWelcomeScope();
                return res;
            });
    }

    // 검색 범위 카드 갱신 — ①법령카드(법령 캐싱/수) ②지역카드(조례 저장/지정 지역)
    function refreshWelcomeScope() {
        var regEl = document.getElementById('usun-scope-region-body');
        if (regEl) {
            if (_pendingRegion > 0) {
                regEl.textContent = '조례 저장 중… (' + _pendingRegion + '건)';
                regEl.classList.remove('muted');
            } else {
                var r = getRegion();
                regEl.textContent = r || '전국 공통 범위';
                regEl.classList.toggle('muted', !r);
            }
        }
        var lawEl = document.getElementById('usun-scope-law-body');
        if (!lawEl) return;
        if (_pendingCache > 0) {   // 진행 중이면 창을 닫아도 카드에 표시
            lawEl.textContent = '캐싱 중… (' + _pendingCache + '건)';
            lawEl.classList.remove('muted');
            return;
        }
        fetch('/monitor', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                // 법령 카드 수는 조례 제외(조례는 지역카드 소관)
                var n = (d.law || []).filter(function (x) { return x.src === 'add' && (x.label || '').indexOf('조례') === -1; }).length;
                lawEl.textContent = n > 0 ? ('추가한 ' + n + '건을 우선 근거로 반영') : '전체 법령·조례에서 검색';
                lawEl.classList.toggle('muted', n === 0);
            })
            .catch(function () { });
    }

    // 지역 자동완성용 지자체 목록(광역시도 + 시/군). 입력하면 datalist로 제안된다.
    // (자치구는 미포함 — 필요 시 직접 입력. 중복 지명은 dedupe.)
    var REGIONS = (function () {
        var s = '서울특별시 부산광역시 대구광역시 인천광역시 광주광역시 대전광역시 울산광역시 세종특별자치시 '
            + '경기도 강원특별자치도 충청북도 충청남도 전북특별자치도 전라남도 경상북도 경상남도 제주특별자치도 '
            + '수원시 성남시 고양시 용인시 부천시 안산시 안양시 남양주시 화성시 평택시 의정부시 시흥시 파주시 김포시 광명시 광주시 군포시 오산시 이천시 양주시 안성시 구리시 포천시 의왕시 하남시 여주시 동두천시 과천시 가평군 양평군 연천군 '
            + '춘천시 원주시 강릉시 동해시 태백시 속초시 삼척시 홍천군 횡성군 영월군 평창군 정선군 철원군 화천군 양구군 인제군 고성군 양양군 '
            + '청주시 충주시 제천시 보은군 옥천군 영동군 증평군 진천군 괴산군 음성군 단양군 '
            + '천안시 공주시 보령시 아산시 서산시 논산시 계룡시 당진시 금산군 부여군 서천군 청양군 홍성군 예산군 태안군 '
            + '전주시 군산시 익산시 정읍시 남원시 김제시 완주군 진안군 무주군 장수군 임실군 순창군 고창군 부안군 '
            + '목포시 여수시 순천시 나주시 광양시 담양군 곡성군 구례군 고흥군 보성군 화순군 장흥군 강진군 해남군 영암군 무안군 함평군 영광군 장성군 완도군 진도군 신안군 '
            + '포항시 경주시 김천시 안동시 구미시 영주시 영천시 상주시 문경시 경산시 의성군 청송군 영양군 영덕군 청도군 고령군 성주군 칠곡군 예천군 봉화군 울진군 울릉군 '
            + '창원시 진주시 통영시 사천시 김해시 밀양시 거제시 양산시 의령군 함안군 창녕군 남해군 하동군 산청군 함양군 거창군 합천군 '
            + '제주시 서귀포시';
        var seen = {}, out = [];
        s.split(/\s+/).forEach(function (r) { if (r && !seen[r]) { seen[r] = 1; out.push(r); } });
        return out;
    })();

    // 지역 설정 모달 — ①지역 선택(답변 반영·지속) 과 ②지역 조례 등록(선택·캐싱)을 명확히 분리.
    // 입력창은 항상 빈칸으로 시작(새로고침해도 텍스트가 남지 않게). 지정된 지역은 상태 칩으로.
    function showRegionModal() {
        var ov = document.getElementById('setup-modal');
        if (ov) ov.remove();
        ov = document.createElement('div');
        ov.id = 'setup-modal';
        ov.innerHTML =
            '<div class="law-list-box" style="max-width:560px">' +
            '<button class="law-list-close" aria-label="닫기">✕</button>' +
            '<h2 style="font-size:18px;margin:0 0 4px">우리 지역 조례</h2>' +
            '<div class="setup-sec-h" style="margin-top:6px">① 지역 선택 <span style="font-weight:400;color:#94a3b8">(답변에 반영)</span></div>' +
            '<div class="law-db-foot" style="margin:0 0 8px">지역을 선택하면 답변 생성 시 해당 지자체를 반영하고, 아래에서 조례를 골라 저장할 수 있습니다.</div>' +
            '<div id="region-status" class="region-status"></div>' +
            '<div class="law-search-bar" style="margin-bottom:0;position:relative">' +
            '<input type="text" id="setup-region" placeholder="지역명 입력 (예: 서 → 서울·서산…)" autocomplete="off" />' +
            '<div id="region-suggest" class="region-suggest" style="display:none"></div>' +
            '</div>' +
            '<div class="setup-sec-h" style="margin-top:20px">② 조례 저장 <span style="font-weight:400;color:#94a3b8">(체크 후 저장)</span></div>' +
            '<div class="law-db-foot" style="margin:0 0 8px">필요한 조례를 체크하고 저장하세요. 저장한 조례는 조문까지 근거로 반영됩니다.</div>' +
            '<input type="text" id="ord-filter" class="ord-filter" placeholder="조례 키워드 필터 (예: 주차·경관·주택…)" autocomplete="off" style="display:none" />' +
            '<div id="setup-region-results" class="law-search-results"></div>' +
            '<div id="region-save-bar" class="region-save-bar" style="display:none">' +
            '<span id="region-check-count" class="region-check-count">0건 선택</span>' +
            '<button type="button" id="setup-region-save" disabled>법규/조례 저장</button>' +
            '</div>' +
            '</div>';
        ov.addEventListener('click', function (e) { if (e.target === ov) ov.remove(); });
        ov.querySelector('.law-list-close').onclick = function () { ov.remove(); };
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { var m = document.getElementById('setup-modal'); if (m) m.remove(); }
        });
        var rin = ov.querySelector('#setup-region');
        var rbox = ov.querySelector('#setup-region-results');
        var rstat = ov.querySelector('#region-status');
        var rsug = ov.querySelector('#region-suggest');
        var rfilter = ov.querySelector('#ord-filter');
        var rsavebar = ov.querySelector('#region-save-bar');
        var rsave = ov.querySelector('#setup-region-save');
        var rcount = ov.querySelector('#region-check-count');
        var _ords = [];   // [{name, cached}]

        // 지역 자동완성 — 입력 즉시 커스텀 드롭다운(datalist '재클릭' 버그 회피). 선택 즉시 조례 로드.
        function regionMatches(q) {
            q = (q || '').trim();
            if (!q) return [];
            var starts = [], has = [];
            for (var i = 0; i < REGIONS.length; i++) {
                var idx = REGIONS[i].indexOf(q);
                if (idx === 0) starts.push(REGIONS[i]);
                else if (idx > 0) has.push(REGIONS[i]);
            }
            return starts.concat(has).slice(0, 12);
        }
        function renderSuggest() {
            var ms = regionMatches(rin.value);
            if (!ms.length) { rsug.style.display = 'none'; rsug.innerHTML = ''; return; }
            rsug.innerHTML = ms.map(function (r) { return '<div class="region-suggest-item" data-r="' + _esc(r) + '">' + _esc(r) + '</div>'; }).join('');
            rsug.style.display = 'block';
        }
        rin.addEventListener('input', renderSuggest);
        rin.addEventListener('focus', renderSuggest);
        rin.addEventListener('blur', function () { setTimeout(function () { rsug.style.display = 'none'; }, 150); });
        rsug.addEventListener('mousedown', function (e) {   // mousedown: blur보다 먼저
            var it = e.target.closest && e.target.closest('.region-suggest-item');
            if (!it) return;
            e.preventDefault();
            rsug.style.display = 'none';
            selectRegion(it.getAttribute('data-r'));   // 선택 즉시 지역 확정 + 조례 로드
        });
        rin.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); selectRegion(rin.value); } });

        function paintStatus() {
            var r = getRegion();
            if (r) {
                rstat.innerHTML = '<span class="region-cur">현재 지역: <b>' + _esc(r) + '</b></span>'
                    + '<button type="button" id="region-clear" class="region-clear">해제</button>';
                rstat.querySelector('#region-clear').addEventListener('click', function () {
                    setRegion(''); refreshWelcomeScope(); paintStatus();
                    _ords = []; rbox.innerHTML = ''; rfilter.style.display = 'none'; rsavebar.style.display = 'none';
                    rbox.innerHTML = '<div class="usun-law-hint">먼저 위에서 지역을 선택하세요.</div>';
                    _toast('지역 지정을 해제했습니다.');
                });
            } else {
                rstat.innerHTML = '<span class="region-cur muted">현재: 전국 공통 범위 (미지정)</span>';
            }
        }

        function updateCount() {
            var n = ov.querySelectorAll('.ord-ck:checked:not(:disabled)').length;
            rcount.textContent = n + '건 선택';
            rsave.disabled = (n === 0);
        }
        // 조례 목록 렌더 — 키워드 필터 적용, 각 항목 체크박스(이미 저장분은 disabled '저장됨')
        function renderOrds(animate) {
            var q = (rfilter.value || '').trim();
            var list = q ? _ords.filter(function (o) { return o.name.indexOf(q) !== -1; }) : _ords;
            var region = getRegion() || '';
            var cachedN = _ords.filter(function (o) { return o.cached; }).length;
            var head = _esc(region) + ' 조례 ' + _ords.length + '건'
                + (cachedN ? (' · <b>저장됨 ' + cachedN + '건</b>') : '')
                + (q ? (' · 필터 ' + list.length + '건') : '');
            if (!list.length) {
                rbox.innerHTML = '<div class="usun-law-hint">' + head + '</div>'
                    + '<div class="usun-law-hint">필터에 맞는 조례가 없습니다.</div>';
                updateCount(); return;
            }
            rbox.innerHTML = '<div class="usun-law-hint">' + head + '</div>'
                + list.map(function (o) {
                    return '<label class="usun-law-item ord-row' + (o.cached ? ' added' : '') + '">'
                        + '<input type="checkbox" class="ord-ck" data-name="' + _esc(o.name) + '"' + (o.cached ? ' checked disabled' : '') + '>'
                        + '<span class="usun-law-kind usun-law-kind-ord">조례</span>'
                        + '<span class="usun-law-nm">' + _esc(o.name) + '</span>'
                        + (o.cached ? '<span class="usun-law-indb">✓ 저장됨</span>' : '')
                        + '</label>';
                }).join('');
            if (animate) { rbox.classList.remove('usun-reveal'); void rbox.offsetWidth; rbox.classList.add('usun-reveal'); }   // 우와아악 등장
            updateCount();
        }
        // 지역의 조례 전부(n=100) + 등록현황 로드 → _ords에 담고 렌더
        function loadOrdinances(region) {
            rfilter.style.display = 'none'; rsavebar.style.display = 'none';
            rbox.innerHTML = '<div class="usun-law-hint">' + _esc(region) + ' 조례 불러오는 중…</div>';
            Promise.all([
                fetch('/law-search?q=' + encodeURIComponent(region) + '&kind=ord&n=100', { credentials: 'same-origin' }).then(function (r) { return r.json(); }),
                fetch('/monitor', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).catch(function () { return {}; })
            ]).then(function (arr) {
                var d = arr[0] || {}, mon = arr[1] || {};
                var rs = (d.results) || [];
                var added = {};
                ['law', 'interp', 'case'].forEach(function (k) {
                    (mon[k] || []).forEach(function (x) { if (x && x.src === 'add') added[(x.label || '').replace(/\s+/g, '')] = 1; });
                });
                _ords = rs.map(function (it) { return { name: it.name, cached: !!added[(it.name || '').replace(/\s+/g, '')] }; });
                if (!_ords.length) { rbox.innerHTML = '<div class="usun-law-hint">이 지역 조례를 찾지 못했습니다 (지역명 확인)</div>'; return; }
                rfilter.style.display = ''; rfilter.value = ''; rsavebar.style.display = 'flex';
                renderOrds(true);
            }).catch(function () { rbox.innerHTML = '<div class="usun-law-hint">검색 실패</div>'; });
        }
        // 지역 선택 확정 — 답변 컨텍스트 지정 + 조례 로드
        function selectRegion(v) {
            v = (v || '').trim();
            if (!v) { rin.focus(); return; }
            setRegion(v); refreshWelcomeScope(); paintStatus();
            rin.value = '';
            _toast("지역 '" + v + "' 선택 — 답변에 반영됩니다.");
            loadOrdinances(v);
        }

        rfilter.addEventListener('input', function () { renderOrds(false); });   // 조례 키워드 필터
        rbox.addEventListener('change', function (e) {
            if (e.target && e.target.classList && e.target.classList.contains('ord-ck')) updateCount();
        });
        // 저장 — 체크된(미저장) 조례를 일괄 캐싱(진행상황은 ②지역카드에 '조례 저장 중')
        rsave.addEventListener('click', function () {
            var cks = Array.prototype.slice.call(ov.querySelectorAll('.ord-ck:checked:not(:disabled)'));
            if (!cks.length) return;
            var names = cks.map(function (c) { return c.getAttribute('data-name'); });
            rsave.disabled = true; rsave.textContent = '저장 중…';
            Promise.all(names.map(function (nm) {
                return cacheLaw('조례', nm).then(function (res) {
                    if (res && !res.error) { var o = _ords.filter(function (x) { return x.name === nm; })[0]; if (o) o.cached = true; }
                });
            })).then(function () {
                rsave.textContent = '법규/조례 저장';
                _toast(names.length + '건 저장했습니다.');
                renderOrds(false);   // 저장됨 표시 갱신
            });
        });

        paintStatus();
        if (getRegion()) loadOrdinances(getRegion());
        else rbox.innerHTML = '<div class="usun-law-hint">먼저 위에서 지역을 선택하세요.</div>';
        document.body.appendChild(ov);
        ov.style.display = 'flex';
        setTimeout(function () { rin.focus(); }, 30);
    }

    // 초기창(SCREEN 1): 로고 → 헤딩 → 참고자료 등록(검색범위) → 입력창 → 예시 칩.
    // body 오버레이(React 밖). 실제 컴포저는 CSS로 화면 밖에 숨기고 히어로 입력이 위임.
    function buildWelcomeCards() {
        var nat = nativeStarterButtons();
        var meta = _startersMeta || {};
        var starters = nat.map(function (b) {
            var lbl = starterLabel(b);          // 원본(메타 조회 키) / plain은 칩 표시용
            var plain = plainStarterLabel(lbl);
            return { label: lbl, plain: plain, msg: (meta[lbl] && meta[lbl].message) || plain };
        }).slice(0, 3);
        var sig = 'hero|' + starters.map(function (s) { return s.label; }).join('|');
        var ov = document.getElementById('usun-welcome-cards');
        if (!(ov && ov.dataset.sig === sig)) {   // 구성이 바뀔 때만 재빌드(멱등 → 루프 없음)
            if (ov) ov.remove();
            ov = document.createElement('div');
            ov.id = 'usun-welcome-cards';
            ov.dataset.sig = sig;

            var hero = _el('div', 'usun-hero');
            // 회사 로고 — 화면 하단 가운데(푸터)에 배치. 외부 이미지 로드 실패 시 숨김.
            var logo = _el('img', 'usun-footer-logo');
            logo.src = 'https://www.usun.co.kr/assets/images/logo.png';
            logo.alt = 'usun';
            logo.onerror = function () { this.style.display = 'none'; };
            hero.appendChild(_el('div', 'usun-hero-h', '무엇을 확인해 드릴까요?'));

            // 입력창(주인공) — mock textarea + 푸터(모델·웹 칩 + 전송)
            var box = _el('div', 'usun-hero-input');
            var ta = _el('textarea', 'usun-hero-ta');
            ta.rows = 1; ta.placeholder = '건축법규 관련 질의를 조문/판례/해석례 근거와 함께 답합니다';
            ta.addEventListener('input', _autoGrow);
            ta.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); heroSend(ta); }
            });
            box.appendChild(ta);
            var foot = _el('div', 'usun-hero-foot');
            var mchip = _el('button', 'usun-hero-chip'); mchip.type = 'button'; mchip.id = 'usun-hero-model';
            mchip.innerHTML = _esc(modelPlainLabel(currentModel())) + ' <span class="usun-chip-caret">▾</span>';
            mchip.addEventListener('click', function (e) { toggleModelMenu(e, mchip); });
            var wchip = _el('button', 'usun-hero-chip'); wchip.type = 'button'; wchip.id = 'usun-hero-web';
            function paintWeb() {
                var on = webSearchOn();
                wchip.textContent = on ? '웹 참고 켬' : '웹 참고 끔';
                wchip.classList.toggle('on', on);
                wchip.setAttribute('aria-pressed', on ? 'true' : 'false');
            }
            paintWeb();
            wchip.addEventListener('click', function () { setWebSearch(!webSearchOn()); paintWeb(); });
            var send = _el('button', 'usun-hero-send'); send.type = 'button'; send.textContent = '↑';
            send.setAttribute('aria-label', '전송');
            send.addEventListener('click', function () { heroSend(ta); });
            foot.appendChild(mchip); foot.appendChild(wchip);
            foot.appendChild(_el('span', 'usun-hero-spacer'));
            foot.appendChild(send);
            box.appendChild(foot);
            hero.appendChild(box);

            // 예시 질문(칩) — 헤더 클릭으로 접기·펴기. 칩 클릭 시 입력창을 채우기만(고쳐 쓰게).
            if (starters.length) {
                var ex = _el('div', 'usun-ex' + (exCollapsed() ? ' collapsed' : ''));
                var exh = _el('div', 'usun-ex-head');
                exh.setAttribute('role', 'button');
                exh.setAttribute('tabindex', '0');
                exh.innerHTML = '<span class="usun-ex-label"><span class="usun-ex-caret" aria-hidden="true">▾</span>예시 질문</span>'
                    + '<span class="usun-ex-hint">예시질의를 통해 모델작동을 확인해보세요.</span>';
                (function () {
                    function toggleEx() { setExCollapsed(ex.classList.toggle('collapsed')); }
                    exh.addEventListener('click', toggleEx);
                    exh.addEventListener('keydown', function (e) {
                        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleEx(); }
                    });
                })();
                ex.appendChild(exh);
                var pills = _el('div', 'usun-ex-pills');
                starters.forEach(function (s) {
                    var p = _el('button', 'usun-ex-pill', s.plain); p.type = 'button';
                    p.addEventListener('click', function () { ta.value = s.msg; _autoGrow.call(ta); ta.focus(); });
                    pills.appendChild(p);
                });
                ex.appendChild(pills);
                hero.appendChild(ex);
            }

            // 질의 가이드 / 참고자료 등록(3 카드) — 헤더 클릭으로 접기·펴기(상태 기억)
            var scope = _el('div', 'usun-scope' + (scopeCollapsed() ? ' collapsed' : ''));
            var sh = _el('div', 'usun-scope-head');
            sh.setAttribute('role', 'button');
            sh.setAttribute('tabindex', '0');
            sh.innerHTML = '<span class="usun-scope-t"><span class="usun-scope-caret" aria-hidden="true">▾</span>질의 가이드 / 참고자료 등록</span>'
                + '<span class="usun-scope-hint">미리 법령/지역 범위를 지정하면 답변생성성능이 개선됩니다.</span>';
            function toggleScope() { setScopeCollapsed(scope.classList.toggle('collapsed')); }
            sh.addEventListener('click', toggleScope);
            sh.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleScope(); }
            });
            scope.appendChild(sh);
            var grid = _el('div', 'usun-scope-grid');
            grid.appendChild(scopeCard('law'));
            grid.appendChild(scopeCard('region'));
            grid.appendChild(scopeCard('doc'));
            scope.appendChild(grid);
            hero.insertBefore(scope, box);   // 참고자료 등록을 입력창 '위'로

            ov.appendChild(hero);
            ov.appendChild(logo);   // 로고는 하단 가운데(히어로 밖, absolute)
            document.body.appendChild(ov);   // body = React 트리 밖 → 크래시 안전
            refreshWelcomeScope();
        }
        // 네이티브 스타터 숨김 + 실제 컴포저는 CSS로 화면 밖에(제출 기능만 유지)
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
            '<h2 style="font-size:18px;margin:0 0 4px">파일 첨부 — 지구단위계획·운영기준 등</h2>' +
            '<div class="law-db-foot" style="margin:0 0 14px">지구단위계획, 지역운영기준 등 API를 통해 접근 불가능한 자료를 첨부해주세요. 첨부한 파일은 이 대화의 참고자료로 적재됩니다.</div>' +
            '<div class="upload-add-bar">' +
            '<label class="upload-add-btn" for="upload-add-input">＋ PDF 파일 추가</label>' +
            '<input type="file" id="upload-add-input" accept="application/pdf,.pdf" hidden />' +
            '<input type="file" id="upload-replace-input" accept="application/pdf,.pdf" hidden />' +
            '<span id="upload-add-status" class="upload-add-status">PDF 파일을 등록합니다.</span>' +
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

    // ── PDF 내보내기 — 전체 대화를 새 창에 통째로 조립 후 인쇄(→'PDF로 저장') ──
    // 라이브 페이지 window.print()는 스크롤 컨테이너의 보이는 부분(1페이지)만 찍혀서,
    // 대화 전체를 새 문서로 만들어 인쇄한다. 표·목록·굵게 등 서식 유지, 액션 버튼 제거.
    function exportPdf() {
        var steps = Array.prototype.slice.call(document.querySelectorAll(
            '[data-step-type="user_message"], [data-step-type="assistant_message"]'));
        if (!steps.length) {
            steps = Array.prototype.slice.call(document.querySelectorAll('[data-testid="step"]'));
        }
        if (!steps.length) { alert('내보낼 대화가 없습니다.'); return; }
        var parts = steps.map(function (el) {
            var isUser = el.getAttribute('data-step-type') === 'user_message';
            return '<div class="msg ' + (isUser ? 'user' : 'assistant') + '">'
                + '<div class="role">' + (isUser ? '질문' : '답변') + '</div>'
                + '<div class="body">' + el.innerHTML + '</div></div>';
        }).join('');
        var w = window.open('', '_blank');
        if (!w) { alert('팝업이 차단되어 PDF 창을 열 수 없습니다. 팝업을 허용한 뒤 다시 시도하세요.'); return; }
        var now = new Date();
        var css =
            'body{font-family:"Malgun Gothic","맑은 고딕",sans-serif;font-size:11pt;line-height:1.65;color:#1a1a1a;max-width:820px;margin:24px auto;padding:0 18px}'
            + 'h1{font-size:15pt;border-bottom:2px solid #333;padding-bottom:8px;margin:0 0 16px}'
            + '.msg{margin:12px 0 18px}'
            + '.role{font-weight:700;font-size:9.5pt;letter-spacing:.02em;color:#1565C0;margin-bottom:5px}'
            + '.msg.user .role{color:#555}'
            + '.msg.user .body{background:#f4f6f9;border-radius:8px;padding:10px 14px}'
            + '.body{word-break:break-word}'
            + '.body button,.body svg,.body [role="button"]{display:none!important}'
            + '.body table{border-collapse:collapse;width:100%;margin:8px 0;font-size:10pt}'
            + '.body td,.body th{border:1px solid #bbb;padding:5px 8px;text-align:left;vertical-align:top}'
            + '.body th{background:#eef1f5}'
            + '.body pre{white-space:pre-wrap;background:#f6f8fa;padding:8px;border-radius:6px}'
            + '.body img{max-width:100%}'
            + '@media print{body{margin:0;max-width:none}a{color:inherit;text-decoration:none}.msg{page-break-inside:auto}}';
        w.document.write('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            + '<title>법령 Q&A 대화</title><style>' + css + '</style></head><body>'
            + '<h1>법령 Q&A 대화 — ' + now.toLocaleString('ko-KR') + '</h1>'
            + parts + '</body></html>');
        w.document.close();
        setTimeout(function () { try { w.focus(); w.print(); } catch (e) { } }, 500);
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

    // ── 입력창(컴포저) 탐색 — 위치·형태 방어 ────────────────────────
    // #chat-submit 에서 위로 훑어 textarea/contenteditable를 품은 컨테이너를 찾고,
    // 못 찾으면 문서 전체(우측바·모달 제외)에서 폴백.
    function _findComposer() {
        var s = document.getElementById('chat-submit');
        if (s) {
            var el = s;
            for (var i = 0; i < 6 && el; i++) {
                var ta = el.querySelector && el.querySelector('textarea, [contenteditable="true"]');
                if (ta) return { ta: ta, submit: s };
                el = el.parentElement;
            }
        }
        var all = Array.prototype.slice.call(
            document.querySelectorAll('textarea, [contenteditable="true"]')
        ).filter(function (t) {
            return !(t.closest && t.closest(
                '#usun-right-bar, #law-search-modal, #law-list-modal, #upload-cache-modal, #evidence-modal, #setup-modal, #usun-welcome-cards'));
        });
        if (all.length) return { ta: all[all.length - 1], submit: s };
        return null;
    }

    // ── 입력창에 텍스트 주입 후 전송 ────────────────────────────────
    function sendPrompt(text) {
        var c = _findComposer();
        if (!c || !c.ta) { alert('입력창을 찾지 못했습니다.'); return false; }
        var ta = c.ta;
        ta.focus();
        if (ta.tagName === 'TEXTAREA') {
            var d = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
            if (d && d.set) d.set.call(ta, text); else ta.value = text;
            ta.dispatchEvent(new Event('input', { bubbles: true }));   // React 상태 반영
        } else {   // contenteditable
            ta.textContent = text;
            ta.dispatchEvent(new InputEvent('input', { bubbles: true }));
        }
        setTimeout(function () {
            var s = c.submit || document.getElementById('chat-submit');
            if (s && !s.disabled) { s.click(); return; }
            ['keydown', 'keypress', 'keyup'].forEach(function (type) {   // 폴백: Enter 전송
                ta.dispatchEvent(new KeyboardEvent(type, {
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                }));
            });
        }, 90);
        return true;
    }

    // 답변 재생성 — 직전 질문을 그대로 재전송
    function regenerateAnswer() {
        var q = lastUserQuestion();
        if (!q) { alert('재생성할 이전 질문이 없습니다.'); return; }
        sendPrompt(q);
    }

    // 근거 더 찾기 — 대화 맥락에서 키워드 도출 → API로 판례·해석례 검색·제안 → 선택 후 재생성
    function findMoreEvidence() {
        var q = lastUserQuestion();
        if (!q) { alert('먼저 질문을 해주세요.'); return; }
        var ans = document.querySelectorAll('[data-step-type="assistant_message"]');
        var lastA = ans.length ? (ans[ans.length - 1].innerText || '').trim() : '';
        showEvidenceModal(q + '\n\n' + lastA, q);
    }

    function showEvidenceModal(ctx, lastQ) {
        var ov = document.getElementById('evidence-modal');
        if (ov) ov.remove();
        ov = document.createElement('div');
        ov.id = 'evidence-modal';
        ov.innerHTML =
            '<div class="law-list-box">' +
            '<button class="law-list-close" aria-label="닫기">✕</button>' +
            '<h2 style="font-size:18px;margin:0 0 4px">근거 더 찾기 — 법령·판례·해석례 제안</h2>' +
            '<div class="law-db-foot" style="margin:0 0 10px">대화에서 키워드를 뽑아 법제처 API로 법령·판례·법령해석례를 검색합니다. 선택해 다시 생성하면, <b>법령은 실제로 캐싱</b>되어 본문까지 반영되고 판례·해석례는 근거로 검토됩니다.</div>' +
            '<div id="ev-keywords" class="ev-keywords"></div>' +
            '<div id="ev-results" class="law-search-results"><div class="usun-law-hint">키워드 도출·검색 중… (몇 초 걸립니다)</div></div>' +
            '<div class="ev-actions"><button type="button" id="ev-gen" disabled>' + genLabel + '</button></div>' +
            '</div>';
        ov.addEventListener('click', function (e) { if (e.target === ov) ov.style.display = 'none'; });
        ov.querySelector('.law-list-close').onclick = function () { ov.style.display = 'none'; };
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { var m = document.getElementById('evidence-modal'); if (m) m.style.display = 'none'; }
        });
        document.body.appendChild(ov);
        ov.style.display = 'flex';

        fetch('/evidence-search', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ context: ctx }),
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var kws = d.keywords || [];
                ov.querySelector('#ev-keywords').innerHTML = kws.length
                    ? ('<span class="ev-kw-l">키워드</span> ' + kws.map(function (k) {
                        return '<span class="ev-kw">' + _esc(k) + '</span>';
                    }).join(' ')) : '';
                var res = ov.querySelector('#ev-results');
                var cs = d.candidates || [];
                if (!cs.length) {
                    res.innerHTML = '<div class="usun-law-hint">관련 법령·판례·해석례를 찾지 못했습니다. (‘＋ 참고자료 추가’로 직접 검색해 보세요)</div>';
                    return;
                }
                res.innerHTML = cs.map(function (it) {
                    var kc = (it.kind === '판례') ? 'case' : (it.kind === '법령') ? 'law' : 'expc';
                    return '<label class="usun-law-item ev-item">'
                        + '<input type="checkbox" class="ev-ck" data-kind="' + _esc(it.kind)
                        + '" data-title="' + _esc(it.title) + '" data-sub="' + _esc(it.sub || '') + '">'
                        + '<span class="usun-law-kind ev-kind-' + kc + '">' + _esc(it.kind) + '</span>'
                        + '<span class="usun-law-nm">' + _esc(it.title)
                        + (it.sub ? (' <span class="ev-sub">' + _esc(it.sub) + '</span>') : '')
                        + '</span></label>';
                }).join('');
                ov.querySelector('#ev-gen').disabled = false;
            })
            .catch(function () {
                ov.querySelector('#ev-results').innerHTML =
                    '<div class="usun-law-hint">검색 실패 (네트워크 또는 API 키 확인)</div>';
            });

        ov.querySelector('#ev-gen').addEventListener('click', function () {
            var checked = Array.prototype.slice.call(ov.querySelectorAll('.ev-ck:checked'));
            if (!checked.length) return;
            ov.style.display = 'none';
            var picks = checked.map(function (c) {
                var sub = c.getAttribute('data-sub');
                return c.getAttribute('data-kind') + ' ' + c.getAttribute('data-title')
                    + (sub ? (' (' + sub + ')') : '');
            });
            // 선택한 '법령'은 실제 캐싱(사각지대 연동) — 본문까지 끌어와 검색에 반영되게
            var lawAdds = checked.filter(function (c) { return c.getAttribute('data-kind') === '법령'; })
                .map(function (c) {
                    return fetch('/law-add', {
                        method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ kind: '법령', name: c.getAttribute('data-title') }),
                    }).catch(function () { });
                });
            var evText = '[사용자가 검토를 요청한 추가 참고자료 — 법령·판례·법령해석례]\n'
                + '아래 자료의 실제 조문·판시·회답 취지를 확인해 관련 있으면 근거로 반영하고, 관련 없으면 배제하라.\n'
                + picks.map(function (p, i) { return (i + 1) + '. ' + p; }).join('\n');
            // 법령 캐싱 완료 후 → 근거를 세션에 숨겨 담고 → 원 질문만 재전송
            Promise.all(lawAdds).then(function () {
                return fetch('/evidence-context', {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: evText }),
                });
            }).then(function () { sendPrompt(lastQ); })
                .catch(function () { sendPrompt(lastQ); });
        });
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
        var hc = document.getElementById('usun-hero-model');   // 히어로 입력 모델 칩 동기화
        if (hc) hc.innerHTML = _esc(modelPlainLabel(id)) + ' <span class="usun-chip-caret">▾</span>';
        pushModel(id);
        closeModelMenu();
    }

    function toggleModelMenu(ev, anchor) {
        ev.stopPropagation();
        if (document.getElementById('model-select-menu')) { closeModelMenu(); return; }
        var btn = anchor || document.getElementById('model-select-btn');
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

    // ── 웹 검색 허용(추가 설정) — localStorage + 서버(/websearch) 동기화 ──────
    var WEB_KEY = 'web_search_enabled';
    function webSearchOn() { try { return localStorage.getItem(WEB_KEY) === '1'; } catch (e) { return false; } }
    function pushWebSearch(on) {
        try {
            fetch('/websearch', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin', body: JSON.stringify({ enabled: !!on })
            });
        } catch (e) { }
    }
    function setWebSearch(on) {
        try { localStorage.setItem(WEB_KEY, on ? '1' : '0'); } catch (e) { }
        pushWebSearch(on);
        _toast(on ? '웹 검색 허용 — 답변 생성에 웹 결과를 함께 참고합니다.' : '웹 검색 꺼짐');
    }
    var webSynced = false;
    function syncWebSearchOnce() {
        // 서버 재시작으로 선호가 비워져도 페이지 로드 시 로컬 값을 재동기화
        if (webSynced) return;
        webSynced = true;
        pushWebSearch(webSearchOn());
    }

    // ── 적용 지역(추가 설정) — 자유 입력. localStorage + 서버(/region) 동기화 ──────
    var REGION_KEY = 'region_pref';
    function getRegion() { try { return localStorage.getItem(REGION_KEY) || ''; } catch (e) { return ''; } }
    function pushRegion(r) {
        try {
            fetch('/region', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin', body: JSON.stringify({ region: r || '' })
            });
        } catch (e) { }
    }
    function setRegion(r) {
        r = (r || '').trim();
        try { localStorage.setItem(REGION_KEY, r); } catch (e) { }
        pushRegion(r);
    }
    var regionSynced = false;
    function syncRegionOnce() {
        if (regionSynced) return;
        regionSynced = true;
        var r = getRegion();
        if (r) pushRegion(r);
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
    // 가벼운 토스트(하단 중앙, 자동 소멸) — 프리셋 완료 등 비차단 알림용
    function _toast(msg) {
        var t = document.createElement('div');
        t.className = 'usun-toast';
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(function () { t.classList.add('show'); }, 10);
        setTimeout(function () { t.classList.remove('show'); }, 2600);
        setTimeout(function () { t.remove(); }, 3000);
    }
    function _monGroup(title, items) {
        if (!items || !items.length) return '';
        var lis = items.map(function (it) {
            var n = (it.n > 1) ? ' <span class="usun-mon-n">×' + it.n + '</span>' : '';
            var isAdd = (it.src === 'add');
            var tag = isAdd ? ' <span class="usun-mon-tag">추가</span>' : '';
            return '<li class="' + (isAdd ? 'usun-mon-add' : '') + '" data-label="' + _esc(it.label)
                + '" title="' + (isAdd ? '직접 추가한 자료(검색·인용 대기)' : '클릭하면 인용 사이드바가 열립니다') + '">'
                + _esc(it.label) + tag + n + '</li>';
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

    // 모니터 항목 라벨에서 매칭 키 추출 (해석례 코드 / 판례 사건번호 / 법령명+조)
    function _sourceKey(label) {
        label = (label || '').trim();
        if (label.indexOf('법제처') === 0) {
            var mc = label.match(/(\d{2}-\d{3,5})/);
            if (mc) return { type: 'code', v: mc[1] };
        }
        var mk = label.match(/(\d{2,4}[가-힣]\d{2,6})/);   // 사건번호(2019두63515 등)
        if (mk) return { type: 'case', v: mk[1] };
        var ml = label.match(/^(.+?)\s*(제\d+조(?:의\d+)?)/);   // 법령명 + 조
        if (ml) return { type: 'law', law: ml[1].trim(), art: ml[2] };
        return { type: 'text', v: label };
    }

    // 모니터 항목 클릭 → 답변 본문의 해당 인용 링크를 찾아 대신 클릭(사이드바 오픈)
    function openSource(label) {
        var key = _sourceKey(label);
        var steps = Array.prototype.slice.call(
            document.querySelectorAll('[data-step-type="assistant_message"]'));
        var cands = [];
        steps.forEach(function (s) {
            Array.prototype.push.apply(cands,
                Array.prototype.slice.call(s.querySelectorAll('a, span, button')));
        });
        function hit(txt) {
            txt = (txt || '').trim();
            if (!txt || txt.length > 90) return false;
            if (key.type === 'law') return txt.indexOf(key.art) !== -1 && txt.indexOf(key.law) !== -1;
            return txt.indexOf(key.v) !== -1;
        }
        var matches = cands.filter(function (el) { return hit(el.textContent); });
        if (!matches.length) return false;
        // 링크(a) → leaf 요소 → 짧은 텍스트 순으로 가장 그럴듯한 인용 링크 선택
        matches.sort(function (a, b) {
            var aw = (a.tagName === 'A') ? 0 : 1, bw = (b.tagName === 'A') ? 0 : 1;
            if (aw !== bw) return aw - bw;
            var al = (a.childElementCount === 0) ? 0 : 1, bl = (b.childElementCount === 0) ? 0 : 1;
            if (al !== bl) return al - bl;
            return (a.textContent || '').length - (b.textContent || '').length;
        });
        matches[0].click();
        return true;
    }

    // 인용자료 스캔 — 지난 답변 텍스트에서 인용된 법령/해석례/판례를 모니터링에 복원
    // (재배포로 서버 누적본이 비워졌을 때 이 대화 기준으로 되살리는 용도)
    function rescanCitations(fresh, silent) {
        var steps = Array.prototype.slice.call(
            document.querySelectorAll('[data-step-type="assistant_message"]'));
        // 사각지대 알림·패치결과·입법요지 등 보조 메시지는 실제 인용이 아니므로 스캔에서 제외
        // (여기 나오는 '「법령」 제N조'는 'API 패치 가능' 후보일 뿐, 답변 본문 인용이 아님)
        var NOTICE = /사각지대 법령 감지|API 패치 가능|패치 결과|캐싱 성공|캐싱 완료|위임 조문 동반|지역 조례 미보유|PDF 직접 첨부/;
        var texts = steps.map(function (el) { return (el.innerText || '').trim(); })
            .filter(function (s) { return s && !NOTICE.test(s); });
        var btn = silent ? null : document.getElementById('rescan-btn');
        if (!texts.length) {
            if (btn) {
                btn.textContent = '스캔할 답변 없음';
                setTimeout(function () { btn.textContent = '🔃 인용자료 스캔'; }, 1500);
            }
            return;
        }
        if (btn) { btn.disabled = true; btn.textContent = '스캔 중…'; }
        fetch('/monitor-rescan', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ texts: texts, fresh: !!fresh }),
        })
            .then(function (r) { return r.json(); })
            .then(function () { refreshMonitor(); })
            .catch(function () { })
            .then(function () {
                if (btn) { btn.disabled = false; btn.textContent = '🔃 인용자료 스캔'; }
            });
    }

    // 모니터링 수동추가 — 모달 결과창에 법령/조례 검색 결과 렌더 (추가는 클릭 위임)
    function doLawSearch(q) {
        var box = document.getElementById('law-search-results');
        if (!box) return;
        q = (q || '').trim();
        if (q.length < 2) { box.innerHTML = '<div class="usun-law-hint">2글자 이상 입력하세요</div>'; return; }
        box.innerHTML = '<div class="usun-law-hint">검색 중…</div>';
        fetch('/law-search?q=' + encodeURIComponent(q) + '&kind=law', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var rs = (d && d.results) || [];
                if (!rs.length) { box.innerHTML = '<div class="usun-law-hint">결과 없음</div>'; return; }
                box.innerHTML = rs.map(function (it) {
                    var k = (it.kind === '조례') ? 'ord' : 'law';
                    // 이미 내장(색인)된 법령은 추가 불필요 — 버튼 대신 '이미 포함됨' 표시
                    var tail = it.in_db
                        ? '<span class="usun-law-indb">이미 포함됨</span>'
                        : '<button type="button" class="usun-law-add">추가</button>';
                    return '<div class="usun-law-item' + (it.in_db ? ' added' : '') + '" data-kind="' + _esc(it.kind) + '" data-name="' + _esc(it.name) + '">'
                        + '<span class="usun-law-kind usun-law-kind-' + k + '">' + _esc(it.kind) + '</span>'
                        + '<span class="usun-law-nm">' + _esc(it.name) + '</span>'
                        + tail + '</div>';
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
            '<h2 style="font-size:18px;margin:0 0 4px">법령 추가</h2>' +
            '<div class="law-db-foot" style="margin:0 0 14px">법제처 API에서 법령을 검색해 캐싱·적재합니다. 이미 내장된 법령은 <b>이미 포함됨</b>으로 표시됩니다. (조례는 “우리 지역 조례”에서 지역별로 등록)</div>' +
            '<div class="law-search-bar">' +
            '<input type="text" id="law-search-q" placeholder="법령명을 입력하세요 (2글자 이상)" />' +
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
            b.disabled = true; b.textContent = '캐싱 중…';
            cacheLaw(item.getAttribute('data-kind'), item.getAttribute('data-name')).then(function (res2) {
                b.textContent = (res2 && !res2.error) ? '✓ 추가됨' : '✗';
                if (res2 && !res2.error) item.classList.add('added'); else b.disabled = false;
            });
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
            syncWebSearchOnce();   // 웹 검색 허용 선호도 서버 재동기화
            syncRegionOnce();      // 적용 지역 선호도 서버 재동기화
            sec('모니터링');
            mk('law-search-btn', '＋ 참고자료 추가', showLawSearchModal);   // 클릭 → 검색·추가 모달
            mk('rescan-btn', '🔃 인용자료 스캔', function () { rescanCitations(true, false); });   // 수동=fresh 재구성
            // 누적 현황
            var mon = document.createElement('div');
            mon.id = 'usun-monitor';
            mon.className = 'usun-monitor';
            bar.appendChild(mon);
            mon.addEventListener('click', function (e) {   // 항목 클릭 → 인용 사이드바 열기
                var li = e.target.closest && e.target.closest('li[data-label]');
                if (li) openSource(li.getAttribute('data-label'));
            });
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

    // 웰컴 오버레이 좌측을 실제 사이드바 폭에 맞춘다 — 사이드바 접힘/리사이즈 시 콘텐츠 재중앙.
    // (CSS의 left:320px는 기본값, 여기서 실측 폭으로 덮어씀)
    function syncWelcomeLeft() {
        var ov = document.getElementById('usun-welcome-cards');
        if (!ov) return;
        var inner = document.querySelector('[data-sidebar="sidebar"]');
        var panel = inner && inner.parentElement;
        var left = 0;
        if (panel) {
            var r = panel.getBoundingClientRect();
            // 접힘이 폭 축소(아이콘 레일)든 슬라이드 아웃(transform)이든 '오른쪽 끝'이 콘텐츠 시작점
            left = Math.max(0, Math.round(r.right));
        }
        var px = left + 'px';
        if (ov.style.left !== px) ov.style.left = px;
    }
    // 사이드바 접힘/펼침은 어트리뷰트 변화(옵저버 미감지) + 애니메이션 → rAF로 매 프레임 추종(부드럽게)
    var _sllRAF = 0;
    function syncWelcomeLeftSoon() {
        var start = Date.now();
        cancelAnimationFrame(_sllRAF);
        (function loop() {
            syncWelcomeLeft();
            if (Date.now() - start < 450) _sllRAF = requestAnimationFrame(loop);
        })();
    }

    function update() {
        loadStartersMeta();
        insertRightBarButtons();
        hideReadme();
        var welcome = !hasMessages();
        // 초기창(SCREEN 1)엔 우측 도구바가 없다 — body 클래스로 우측 바·실제 컴포저를 숨긴다.
        document.body.classList.toggle('usun-welcome-mode', welcome);
        if (!welcome) {
            removeLogo();   // 혹시 남은 구버전 로고(#usun-logo-wrap) 정리
            teardownWelcomeCards();
        } else {
            try { buildWelcomeCards(); } catch (e) { }   // 히어로 오버레이 렌더
            syncWelcomeLeft();   // 좌측 사이드바 폭/접힘에 맞춰 히어로 재중앙
        }
        insertSidebarResizeHandle();
        killDarkMode();
    }

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    // 사이드바 토글/리사이즈 → 웰컴 히어로 재중앙(옵저버가 못 잡는 어트리뷰트 변화 대응)
    document.addEventListener('click', syncWelcomeLeftSoon, true);
    window.addEventListener('resize', syncWelcomeLeft);

    // 대화 전환 감지(첫 사용자 메시지) + 답변 변화 감지(어시스턴트 수·마지막 길이)
    var _lastConvSig = '', _lastAnsSig = '';
    function _convSig() {
        var u = document.querySelector('[data-step-type="user_message"]');
        return u ? (u.innerText || '').trim().slice(0, 80) : '';
    }
    function _ansSig() {
        var a = document.querySelectorAll('[data-step-type="assistant_message"]');
        var last = a.length ? (a[a.length - 1].innerText || '') : '';
        return a.length + '|' + last.length;
    }
    // 4초 폴링: ①대화 전환→fresh 재스캔 ②새 답변/스트리밍 변화→병합 재스캔(자동) ③그 외 갱신
    setInterval(function () {
        if (!document.getElementById('usun-monitor')) return;
        if (document.getElementById('usun-welcome-cards')) { refreshWelcomeScope(); syncWelcomeLeft(); }   // 웰컴이면 검색범위·좌측정렬 갱신
        var sig = _convSig();
        if (sig !== _lastConvSig) {
            var switched = (_lastConvSig && sig);   // A→B (둘 다 비어있지 않음 = 실제 전환)
            _lastConvSig = sig;
            if (switched) { rescanCitations(true, true); _lastAnsSig = _ansSig(); return; }
        }
        var asig = _ansSig();
        if (asig !== _lastAnsSig) {   // 답변 생성/스트리밍 변화 → fresh 재스캔(허수 누적 방지, 수동추가분 보존)
            _lastAnsSig = asig;
            rescanCitations(true, true);
            return;
        }
        refreshMonitor();
    }, 4000);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', update);
    } else {
        update();
    }
})();

