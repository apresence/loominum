/**
 * Event Capture Script
 * 
 * Records user interactions on a web page, including clicks, dropdown selections,
 * and element enabled/disabled state changes. Each event is captured with a timestamp,
 * element details (id, name, type, visible text), and event type.
 * 
 * Events are:
 * - Logged to console as JSON strings
 * - Stored in the `events` array
 * - Retrievable via get_events() as newline-delimited string
 * 
 * Usage:
 *   Inject into page or paste in console, then call get_events() to retrieve all events.
 */

// Events array to store all recorded events
const events = [];

// Helper function to get visible text from an element
function getVisibleText(element) {
    // For select elements, get the selected option's text
    if (element.tagName === 'SELECT' && element.selectedOptions && element.selectedOptions.length > 0) {
        return element.selectedOptions[0].text || element.selectedOptions[0].value || '';
    }
    
    // Try various properties to get visible text
    if (element.value !== undefined && element.value !== '') {
        return element.value;
    }
    if (element.innerText && element.innerText.trim()) {
        return element.innerText.trim();
    }
    if (element.textContent && element.textContent.trim()) {
        return element.textContent.trim();
    }
    if (element.alt) {
        return element.alt;
    }
    if (element.title) {
        return element.title;
    }
    if (element.placeholder) {
        return element.placeholder;
    }
    if (element.ariaLabel) {
        return element.ariaLabel;
    }
    return '';
}

// Helper function to record an event
function recordEvent(eventType, element) {
    const eventData = {
        ts: Date.now(),
        el: {
            id: element.id || '',
            name: element.name || '',
            type: element.type || element.tagName.toLowerCase(),
            caption: getVisibleText(element)
        },
        evt: eventType
    };
    
    const eventStr = JSON.stringify(eventData);
    events.push(eventStr);
    console.log(eventStr);
}

// Listen for click events
document.addEventListener('click', function(e) {
    recordEvent('clicked', e.target);
}, true);

// Listen for dropdown (select) changes
document.addEventListener('change', function(e) {
    if (e.target.tagName === 'SELECT') {
        recordEvent('selected', e.target);
    }
}, true);

// Listen for element enabled/disabled changes using MutationObserver
const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
        if (mutation.type === 'attributes' && mutation.attributeName === 'disabled') {
            const element = mutation.target;
            const isDisabled = element.hasAttribute('disabled');
            recordEvent(isDisabled ? 'disabled' : 'enabled', element);
        }
    });
});

// Start observing when DOM is ready
function startObserving() {
    if (document.body) {
        observer.observe(document.body, {
            attributes: true,
            attributeFilter: ['disabled'],
            subtree: true
        });
    } else {
        setTimeout(startObserving, 100);
    }
}

// Initialize observer
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startObserving);
} else {
    startObserving();
}

// Function to get all events as line-delimited string
function get_events() {
    return events.join('\n');
}