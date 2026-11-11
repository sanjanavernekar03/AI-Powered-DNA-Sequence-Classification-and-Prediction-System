/**
 * Global AI Chatbot & Voice Assistant Frontend Controller
 */

document.addEventListener("DOMContentLoaded", function () {
    const toggleBtn = document.getElementById("chatbot-toggle-btn");
    const panel = document.getElementById("chatbot-panel");
    const closeBtn = document.getElementById("chatbot-close-btn");
    const conversation = document.getElementById("chatbot-conversation");
    const form = document.getElementById("chatbot-form");
    const input = document.getElementById("chatbot-input");
    const langSelect = document.getElementById("chatbot-lang-select");
    const voiceInputBtn = document.getElementById("btn-voice-input");
    const voiceOutputBtn = document.getElementById("btn-voice-output-toggle");
    const voiceStatus = document.getElementById("voice-status-text");
    const suggestions = document.querySelectorAll("[data-chat-prompt]");

    let isAudioOutputEnabled = true;
    const conversationHistory = [];
    let userCoords = null;

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            function (pos) {
                userCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
            },
            function () {},
            { timeout: 5000 }
        );
    }

    if (!toggleBtn || !panel) return;

    suggestions.forEach(function (suggestion) {
        suggestion.addEventListener("click", function () {
            const currentLang = (langSelect ? langSelect.value : ((window.LanguageManager && window.LanguageManager.getLanguage) ? window.LanguageManager.getLanguage() : 'en'));
            let prompt = suggestion.dataset.chatPrompt;
            if (currentLang !== 'en' && suggestion.textContent.trim()) {
                prompt = suggestion.textContent.trim();
            }
            if (prompt) sendMessage(prompt);
        });
    });

    // Toggle Chatbot Panel
    toggleBtn.addEventListener("click", function () {
        panel.classList.toggle("d-none");
        if (!panel.classList.contains("d-none")) {
            input.focus();
            if (navigator.geolocation && !userCoords) {
                navigator.geolocation.getCurrentPosition(
                    function (pos) {
                        userCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
                    },
                    function () {},
                    { timeout: 3000 }
                );
            }
        }
    });

    closeBtn.addEventListener("click", function () {
        panel.classList.add("d-none");
        if (window.VoiceAssistant) window.VoiceAssistant.stopSpeaking();
    });

    function updateVoiceOutputBtnState(speaking) {
        if (!voiceOutputBtn) return;
        const icon = voiceOutputBtn.querySelector("i");
        const label = document.getElementById("voice-output-label");
        if (speaking) {
            voiceOutputBtn.classList.add("btn-danger", "active");
            voiceOutputBtn.classList.remove("btn-outline-primary", "btn-outline-secondary");
            if (icon) icon.className = "bi bi-stop-circle-fill me-1";
            if (label) label.textContent = getI18nText("js_stop", "Stop");
        } else {
            voiceOutputBtn.classList.remove("btn-danger");
            voiceOutputBtn.classList.add("btn-outline-primary", "active");
            if (icon) icon.className = "bi bi-volume-up-fill me-1";
            if (label) label.textContent = getI18nText("chat_listen_btn", "Listen");
        }
    }

    // Voice Output / Listen Button
    if (voiceOutputBtn) {
        voiceOutputBtn.addEventListener("click", function () {
            if (window.VoiceAssistant && window.VoiceAssistant.isSpeaking) {
                window.VoiceAssistant.stopSpeaking();
                updateVoiceOutputBtnState(false);
                return;
            }

            const currentLang = (langSelect ? langSelect.value : ((window.LanguageManager && window.LanguageManager.getLanguage) ? window.LanguageManager.getLanguage() : 'en'));

            let textToSpeak = "";
            const assistantBubbles = Array.from(document.querySelectorAll("#chatbot-conversation .assistant-msg .msg-bubble"));
            const lastAssistantBubble = assistantBubbles.pop();
            if (lastAssistantBubble) {
                const contentEl = lastAssistantBubble.querySelector("[data-i18n='auto_153334']") || 
                                  lastAssistantBubble.querySelector(".chatbot-msg-content") || 
                                  lastAssistantBubble.querySelector("div[style*='font-size: 0.9rem']");
                if (contentEl && contentEl.innerText.trim()) {
                    textToSpeak = contentEl.innerText.trim();
                }
            }
            if (!textToSpeak) {
                textToSpeak = getI18nText("auto_153334", "Hello! How can I assist you with your health or genetic analysis today?");
            }

            if (textToSpeak && window.VoiceAssistant) {
                updateVoiceOutputBtnState(true);
                window.VoiceAssistant.speakWithCallback(textToSpeak, currentLang, function () {
                    updateVoiceOutputBtnState(false);
                });
            }
        });
    }

    function getI18nText(key, defaultText) {
        const lang = (window.LanguageManager && window.LanguageManager.getLanguage) ? window.LanguageManager.getLanguage() : 'en';
        if (window.TRANSLATIONS && window.TRANSLATIONS[lang] && window.TRANSLATIONS[lang][key]) {
            return window.TRANSLATIONS[lang][key];
        }
        return defaultText;
    }

    // Voice Input Speech Recognition
    if (voiceInputBtn) {
        voiceInputBtn.addEventListener("click", function () {
            const lang = langSelect ? langSelect.value : ((window.LanguageManager && window.LanguageManager.getLanguage) ? window.LanguageManager.getLanguage() : 'en');
            if (window.VoiceAssistant && window.VoiceAssistant.isListening) {
                window.VoiceAssistant.stopListening();
                voiceInputBtn.classList.remove("btn-danger");
                voiceInputBtn.classList.add("btn-outline-emerald");
                voiceStatus.textContent = "";
                return;
            }

            voiceInputBtn.classList.remove("btn-outline-emerald");
            voiceInputBtn.classList.add("btn-danger");
            voiceStatus.textContent = getI18nText('js_listening', 'Listening...');

            window.VoiceAssistant.startListening(
                lang,
                function (transcript) {
                    input.value = transcript;
                    voiceStatus.textContent = getI18nText('js_processing', 'Processing speech...');
                    sendMessage(transcript);
                },
                function (err) {
                    voiceStatus.textContent = getI18nText('js_mic_error', 'Mic error:') + " " + err;
                    voiceInputBtn.classList.remove("btn-danger");
                    voiceInputBtn.classList.add("btn-outline-emerald");
                },
                function () {
                    voiceInputBtn.classList.remove("btn-danger");
                    voiceInputBtn.classList.add("btn-outline-emerald");
                    voiceStatus.textContent = "";
                }
            );
        });
    }

    // Send Form Submission
    if (form) {
        form.addEventListener("submit", function (e) {
            e.preventDefault();
            const text = input.value.strip ? input.value.strip() : input.value.trim();
            if (text) {
                sendMessage(text);
            }
        });
    }

    function sendMessage(text) {
        appendMessage("user", text);
        input.value = "";

        const currentLang = (langSelect ? langSelect.value : (window.LanguageManager && window.LanguageManager.getLanguage ? window.LanguageManager.getLanguage() : 'en'));
        const currentPath = window.location.pathname;

        // Immediately append assistant streaming message container
        const streamMsg = appendStreamingAssistantMessage();

        let accumulatedText = "";
        let hasReceivedToken = false;

        fetch("/api/chatbot/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                message: text,
                current_page: currentPath,
                language: currentLang,
                conversation: conversationHistory.slice(-4),
                user_location: userCoords
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error("Stream HTTP " + response.status);
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            function readStream() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        finalizeMessage();
                        return;
                    }

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split("\n\n");
                    buffer = lines.pop(); // keep remainder

                    for (const block of lines) {
                        const line = block.trim();
                        if (line.startsWith("data:")) {
                            try {
                                const data = JSON.parse(line.substring(5).trim());
                                if (data.token) {
                                    if (!hasReceivedToken) {
                                        hasReceivedToken = true;
                                        streamMsg.clearTypingIndicator();
                                    }
                                    accumulatedText += data.token;
                                    streamMsg.updateText(accumulatedText);
                                } else if (data.done) {
                                    if (data.full_response && !accumulatedText) {
                                        accumulatedText = data.full_response;
                                        streamMsg.updateText(accumulatedText);
                                    }
                                } else if (data.error) {
                                    streamMsg.clearTypingIndicator();
                                    streamMsg.updateText("Error: " + data.error);
                                }
                            } catch (e) {
                                // ignore parse errors on partial chunks
                            }
                        }
                    }

                    return readStream();
                });
            }

            return readStream();
        })
        .catch(err => {
            console.warn("Chatbot stream fallback to /chat:", err);
            // Fallback to standard chat endpoint if streaming fails
            fetch("/api/chatbot/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    current_page: currentPath,
                    language: currentLang,
                    conversation: conversationHistory.slice(-4),
                    user_location: userCoords
                })
            })
            .then(res => res.json())
            .then(data => {
                streamMsg.clearTypingIndicator();
                if (data.error) {
                    streamMsg.updateText("Error: " + data.error);
                } else {
                    accumulatedText = data.response;
                    finalizeMessage();
                }
            })
            .catch(() => {
                streamMsg.clearTypingIndicator();
                streamMsg.updateText(getI18nText('js_cannot_connect', 'Unable to connect to assistant backend.'));
            });
        });

        function finalizeMessage() {
            if (!accumulatedText) return;
            streamMsg.finalize(accumulatedText);
            conversationHistory.push({ role: "user", content: text });
            conversationHistory.push({ role: "assistant", content: accumulatedText });

            if (isAudioOutputEnabled && window.VoiceAssistant) {
                try {
                    updateVoiceOutputBtnState(true);
                    window.VoiceAssistant.speakWithCallback(accumulatedText, currentLang, function () {
                        updateVoiceOutputBtnState(false);
                    });
                } catch (audioErr) {
                    console.warn("Speech playback error:", audioErr);
                    updateVoiceOutputBtnState(false);
                }
            }
        }
    }

    function wireBubbleSpeaker(bubbleDiv, textToSpeak) {
        if (!bubbleDiv || !textToSpeak) return;
        const btn = bubbleDiv.querySelector(".btn-speak-bubble");
        if (!btn) return;
        btn.onclick = function (e) {
            e.stopPropagation();
            if (window.VoiceAssistant && window.VoiceAssistant.isSpeaking) {
                window.VoiceAssistant.stopSpeaking();
                btn.innerHTML = '<i class="bi bi-volume-up-fill text-primary"></i> <span class="small" style="font-size: 0.75rem;">' + getI18nText('chat_listen_btn', 'Listen') + '</span>';
                updateVoiceOutputBtnState(false);
                return;
            }

            const currentLang = (langSelect ? langSelect.value : ((window.LanguageManager && window.LanguageManager.getLanguage) ? window.LanguageManager.getLanguage() : 'en'));
            btn.innerHTML = '<i class="bi bi-stop-circle-fill text-danger"></i> <span class="small" style="font-size: 0.75rem;">' + getI18nText('js_stop', 'Stop') + '</span>';
            updateVoiceOutputBtnState(true);

            // Dynamically fetch current text from the bubble so it reflects the active translation
            let textToPlay = textToSpeak;
            const contentEl = bubbleDiv.querySelector("[data-i18n='auto_153334']") || 
                              bubbleDiv.querySelector(".chatbot-msg-content") || 
                              bubbleDiv.querySelector("div[style*='font-size: 0.9rem']");
            if (contentEl && contentEl.innerText.trim()) {
                textToPlay = contentEl.innerText.trim();
            }

            try {
                window.VoiceAssistant.speakWithCallback(textToPlay, currentLang, function () {
                    btn.innerHTML = '<i class="bi bi-volume-up-fill text-primary"></i> <span class="small" style="font-size: 0.75rem;">' + getI18nText('chat_listen_btn', 'Listen') + '</span>';
                    updateVoiceOutputBtnState(false);
                });
            } catch (err) {
                console.warn("Speech playback error:", err);
                btn.innerHTML = '<i class="bi bi-volume-up-fill text-primary"></i> <span class="small" style="font-size: 0.75rem;">' + getI18nText('chat_listen_btn', 'Listen') + '</span>';
                updateVoiceOutputBtnState(false);
            }
        };
    }

    function appendStreamingAssistantMessage() {
        const msgDiv = document.createElement("div");
        msgDiv.className = "chat-message assistant-msg mb-3";

        const bubbleDiv = document.createElement("div");
        bubbleDiv.className = "msg-bubble assistant-bubble shadow-sm";

        const headerDiv = document.createElement("div");
        headerDiv.className = "d-flex justify-content-between align-items-center mb-1";
        headerDiv.innerHTML = `
            <span class="fw-semibold text-emerald small"><i class="bi bi-robot me-1"></i>DNAura Assistant</span>
            <button type="button" class="btn btn-sm btn-link p-0 text-decoration-none text-muted btn-speak-bubble" title="Listen" style="font-size: 0.75rem;">
                <i class="bi bi-volume-up-fill text-primary"></i> <span class="small" style="font-size: 0.75rem;">${getI18nText('chat_listen_btn', 'Listen')}</span>
            </button>
        `;

        const contentDiv = document.createElement("div");
        contentDiv.className = "stream-content";
        contentDiv.innerHTML = `
            <div class="d-flex align-items-center py-1">
                <span class="spinner-grow spinner-grow-sm text-emerald me-2" role="status" style="width: 0.85rem; height: 0.85rem;"></span>
                <span class="small text-muted">${getI18nText('js_assistant_thinking', 'Generating answer...')}</span>
            </div>
        `;

        bubbleDiv.appendChild(headerDiv);
        bubbleDiv.appendChild(contentDiv);
        msgDiv.appendChild(bubbleDiv);
        conversation.appendChild(msgDiv);
        conversation.scrollTop = conversation.scrollHeight;

        return {
            element: msgDiv,
            clearTypingIndicator: function () {
                contentDiv.innerHTML = "";
            },
            updateText: function (rawText) {
                contentDiv.innerHTML = formatChatbotText(rawText);
                conversation.scrollTop = conversation.scrollHeight;
            },
            finalize: function (rawText) {
                contentDiv.innerHTML = formatChatbotText(rawText);
                conversation.scrollTop = conversation.scrollHeight;
                wireBubbleSpeaker(bubbleDiv, rawText);
            }
        };
    }

    function formatChatbotText(text) {
        let formattedText = escapeHtml(text);
        formattedText = formattedText.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
        formattedText = formattedText.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
            if (url.includes('/appointments/book')) {
                return `<a href="${url}" class="btn btn-sm btn-primary me-1 my-1 text-white text-decoration-none d-inline-flex align-items-center" style="font-size: 0.8rem; padding: 4px 10px; border-radius: 6px;"><i class="bi bi-calendar-plus me-1"></i>${label}</a>`;
            }
            if (url.includes('/hospitals/')) {
                return `<a href="${url}" class="btn btn-sm btn-outline-primary me-1 my-1 text-decoration-none d-inline-flex align-items-center" style="font-size: 0.8rem; padding: 4px 10px; border-radius: 6px;"><i class="bi bi-hospital me-1"></i>${label}</a>`;
            }
            if (url.includes('google.com/maps') || url.includes('maps.google')) {
                return `<a href="${url}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-danger me-1 my-1 text-decoration-none d-inline-flex align-items-center" style="font-size: 0.8rem; padding: 4px 10px; border-radius: 6px;"><i class="bi bi-geo-alt-fill me-1"></i>${label}</a>`;
            }
            return `<a href="${url}" class="text-primary text-decoration-underline" target="_blank">${label}</a>`;
        });
        formattedText = formattedText.replace(/\n/g, "<br>");
        return formattedText;
    }

    function appendMessage(sender, text, disclaimer) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `chat-message ${sender}-msg mb-3`;

        let html = "";
        if (sender === "user") {
            html = `
                <div class="msg-bubble user-bubble shadow-sm">
                    <div>${escapeHtml(text)}</div>
                </div>
            `;
            msgDiv.innerHTML = html;
        } else {
            let formattedText = formatChatbotText(text);

            html = `
                <div class="msg-bubble assistant-bubble shadow-sm">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-semibold text-emerald small"><i class="bi bi-robot me-1"></i>DNAura Assistant</span>
                        <button type="button" class="btn btn-sm btn-link p-0 text-decoration-none text-muted btn-speak-bubble" title="Listen" style="font-size: 0.75rem;">
                            <i class="bi bi-volume-up-fill text-primary"></i> <span class="small" style="font-size: 0.75rem;">${getI18nText('chat_listen_btn', 'Listen')}</span>
                        </button>
                    </div>
                    <div>${formattedText}</div>
                </div>
            `;
            msgDiv.innerHTML = html;
            wireBubbleSpeaker(msgDiv.querySelector(".msg-bubble"), text);
        }

        conversation.appendChild(msgDiv);
        conversation.scrollTop = conversation.scrollHeight;
    }

    // Wire initial greeting bubble speaker button if present
    const initialGreetingBubble = document.querySelector("#chatbot-conversation .assistant-msg .msg-bubble");
    if (initialGreetingBubble) {
        const greetingTextEl = initialGreetingBubble.querySelector("[data-i18n='auto_153334']");
        const greetingText = greetingTextEl ? greetingTextEl.innerText : "Hello! How can I assist you with your health or genetic analysis today?";
        wireBubbleSpeaker(initialGreetingBubble, greetingText);
    }

    // Expose ChatbotUI globally for Voice Assistant integration
    window.ChatbotUI = {
        appendMessage: appendMessage,
        sendMessage: sendMessage
    };

    function escapeHtml(unsafe) {
        return unsafe
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }

    function updateChatbotLanguage(newLang) {
        // 1. Update initial greeting message
        const greetingEl = document.querySelector("#chatbot-conversation .assistant-msg [data-i18n='auto_153334']");
        if (greetingEl) {
            greetingEl.textContent = getI18nText("auto_153334", "Hello! How can I assist you with your health or genetic analysis today?");
        }

        // 2. Update assistant name badge
        const botNameEl = document.querySelector("#chatbot-conversation .assistant-msg [data-i18n='auto_54a385']");
        if (botNameEl) {
            botNameEl.innerHTML = '<i class="bi bi-robot me-1"></i>' + getI18nText("auto_54a385", "DNAura Assistant");
        }

        // 3. Update suggestion chips
        suggestions.forEach(s => {
            const i18nKey = s.getAttribute("data-i18n");
            if (i18nKey) {
                s.textContent = getI18nText(i18nKey, s.dataset.chatPrompt || s.textContent);
            }
        });

        // 5. Update bubble listen buttons
        document.querySelectorAll("#chatbot-conversation .btn-speak-bubble span").forEach(span => {
            span.textContent = getI18nText("chat_listen_btn", "Listen");
        });

        // 6. Update toolbar controls
        const voiceInLabel = document.getElementById("voice-input-label");
        if (voiceInLabel) voiceInLabel.textContent = getI18nText("bot_voice_btn", "Voice Input");
        const voiceOutLabel = document.getElementById("voice-output-label");
        if (voiceOutLabel) voiceOutLabel.textContent = getI18nText("chat_listen_btn", "Listen");
        if (input) input.setAttribute("placeholder", getI18nText("bot_input_ph", "Type a message..."));
    }

    if (langSelect) {
        langSelect.addEventListener("change", function () {
            updateChatbotLanguage(langSelect.value);
        });
    }
    window.addEventListener("languageChanged", function (e) {
        if (langSelect && e.detail && e.detail.language && langSelect.value !== e.detail.language) {
            langSelect.value = e.detail.language;
        }
        updateChatbotLanguage(e.detail ? e.detail.language : null);
    });

    // Run once on load
    setTimeout(updateChatbotLanguage, 50);
});

