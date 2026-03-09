// content/index.js
import { record } from 'rrweb';

let events = [];

// Nagrywanie DOM (rrweb)
record({
    emit(event) {
        events.push(event);
        // Co 5s wysyłaj paczkę do background.js
        if (events.length > 50) {
            chrome.runtime.sendMessage({ type: 'record', payload: [...events] });
            events = [];
        }
    },
});

// Nasłuchiwanie kliknięć (Twoja logika z MVP)
document.addEventListener('click', (e) => {
    chrome.runtime.sendMessage({
        type: 'track',
        payload: {
            type: 'click',
            details: {
                tagName: e.target.tagName.toLowerCase(),
                path: getCssPath(e.target),
                text: e.target.innerText?.substring(0, 50)
            }
        }
    });
}, true);

// Funkcja pomocnicza z Twojego MVP
function getCssPath(el) {
    if (!(el instanceof Element)) return;
    const path = [];
    while (el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.nodeName.toLowerCase();
        if (el.id) {
            selector += '#' + el.id;
            path.unshift(selector);
            break;
        } else {
            let sib = el, nth = 1;
            while (sib = sib.previousElementSibling) {
                if (sib.nodeName.toLowerCase() == selector) nth++;
            }
            if (nth != 1) selector += ":nth-of-type("+nth+")";
        }
        path.unshift(selector);
        el = el.parentNode;
    }

    return el.tagName.toLowerCase(); // uproszczenie dla przykładu
}