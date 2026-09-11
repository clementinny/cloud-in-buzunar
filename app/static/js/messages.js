const contactsList = document.querySelector("#contacts-list");
const contactsEmpty = document.querySelector("#contacts-empty");
const refreshContactsButton = document.querySelector(
    "#refresh-contacts",
);
const signedInUser = document.querySelector("#signed-in-user");
const conversationPlaceholder = document.querySelector(
    "#conversation-placeholder",
);
const conversation = document.querySelector("#conversation");
const conversationName = document.querySelector("#conversation-name");
const conversationRole = document.querySelector("#conversation-role");
const messageList = document.querySelector("#message-list");
const messageForm = document.querySelector("#message-form");
const messageContent = document.querySelector("#message-content");
const sendMessageButton = document.querySelector("#send-message");
const messageStatus = document.querySelector("#message-status");
const messageCounter = document.querySelector("#message-counter");
const messagesError = document.querySelector("#messages-error");

let selectedContactId = null;
let lastMessageId = 0;
let contactsLoading = false;
let conversationLoading = false;


function showPageError(message) {
    messagesError.textContent = message;
    messagesError.hidden = false;
}


function clearPageError() {
    messagesError.textContent = "";
    messagesError.hidden = true;
}


async function readJsonResponse(response) {
    let data = {};

    try {
        data = await response.json();
    } catch (_error) {
        data = {};
    }

    if (response.status === 401) {
        window.location.assign("/");
        throw new Error("Sesiunea a expirat.");
    }

    if (!response.ok) {
        throw new Error(
            data.error ?? `Cererea a eșuat: HTTP ${response.status}`,
        );
    }

    return data;
}


function formatContactTime(value) {
    if (!value) {
        return "";
    }

    return new Intl.DateTimeFormat("ro-RO", {
        hour: "2-digit",
        minute: "2-digit",
    }).format(new Date(value));
}


function formatMessageTime(value) {
    return new Intl.DateTimeFormat("ro-RO", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    }).format(new Date(value));
}


function createContactButton(contact) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "contact-button";
    button.dataset.contactId = String(contact.id);
    button.classList.toggle(
        "is-active",
        contact.id === selectedContactId,
    );

    const name = document.createElement("span");
    name.className = "contact-name";
    name.textContent = contact.username;

    const time = document.createElement("span");
    time.className = "contact-time";
    time.textContent = formatContactTime(contact.last_message_at);

    const preview = document.createElement("span");
    preview.className = "contact-preview";
    preview.textContent = contact.last_message ?? "Conversație nouă";

    button.append(name, time, preview);

    if (contact.unread_count > 0) {
        const unread = document.createElement("span");
        unread.className = "unread-badge";
        unread.textContent = String(contact.unread_count);
        unread.setAttribute(
            "aria-label",
            `${contact.unread_count} mesaje necitite`,
        );
        button.append(unread);
    } else {
        button.append(document.createElement("span"));
    }

    button.addEventListener("click", () => {
        selectContact(contact);
    });

    return button;
}


async function loadContacts({quiet = false} = {}) {
    if (contactsLoading) {
        return;
    }

    contactsLoading = true;

    try {
        const response = await fetch("/api/messages/contacts");
        const data = await readJsonResponse(response);

        contactsList.replaceChildren(
            ...data.contacts.map(createContactButton),
        );
        contactsEmpty.hidden = data.contacts.length !== 0;

        if (selectedContactId !== null) {
            const selectedContact = data.contacts.find(
                (contact) => contact.id === selectedContactId,
            );

            if (selectedContact === undefined) {
                selectedContactId = null;
                conversation.hidden = true;
                conversationPlaceholder.hidden = false;
            }
        }

        if (!quiet) {
            clearPageError();
        }
    } catch (error) {
        if (!quiet) {
            showPageError(error.message);
        }
    } finally {
        contactsLoading = false;
    }
}


function createMessageBubble(message) {
    const bubble = document.createElement("article");
    bubble.className = "message-bubble";
    bubble.classList.toggle("is-mine", message.is_mine);
    bubble.dataset.messageId = String(message.id);

    const content = document.createElement("p");
    content.className = "message-text";
    content.textContent = message.content;

    const time = document.createElement("time");
    time.className = "message-time";
    time.dateTime = message.created_at;
    time.textContent = formatMessageTime(message.created_at);

    bubble.append(content, time);
    return bubble;
}


function appendMessages(messages, {replace = false} = {}) {
    if (replace) {
        messageList.replaceChildren();
        lastMessageId = 0;
    }

    const emptyMessage = messageList.querySelector(".message-empty");
    emptyMessage?.remove();

    for (const message of messages) {
        if (
            messageList.querySelector(
                `[data-message-id="${message.id}"]`,
            )
        ) {
            continue;
        }

        messageList.append(createMessageBubble(message));
        lastMessageId = Math.max(lastMessageId, message.id);
    }

    if (messageList.children.length === 0) {
        const empty = document.createElement("p");
        empty.className = "message-empty";
        empty.textContent = "Nu există mesaje. Poți începe conversația.";
        messageList.append(empty);
    }

    if (messages.length > 0 || replace) {
        messageList.scrollTop = messageList.scrollHeight;
    }
}


async function loadConversation({initial = false, quiet = false} = {}) {
    if (selectedContactId === null || conversationLoading) {
        return;
    }

    conversationLoading = true;
    const requestedContactId = selectedContactId;
    const query = new URLSearchParams();

    if (!initial && lastMessageId > 0) {
        query.set("after_id", String(lastMessageId));
    }

    const suffix = query.size > 0 ? `?${query.toString()}` : "";

    try {
        const response = await fetch(
            `/api/messages/conversations/${requestedContactId}${suffix}`,
        );
        const data = await readJsonResponse(response);

        if (requestedContactId !== selectedContactId) {
            return;
        }

        conversationName.textContent = data.contact.username;
        conversationRole.textContent =
            data.contact.role === "admin"
                ? "Administrator"
                : "Utilizator activ";
        appendMessages(data.messages, {replace: initial});

        if (!quiet) {
            clearPageError();
        }

        await loadContacts({quiet: true});
    } catch (error) {
        if (!quiet) {
            showPageError(error.message);
        }
    } finally {
        conversationLoading = false;
    }
}


function selectContact(contact) {
    selectedContactId = contact.id;
    lastMessageId = 0;
    conversationName.textContent = contact.username;
    conversationRole.textContent =
        contact.role === "admin" ? "Administrator" : "Utilizator activ";
    conversationPlaceholder.hidden = true;
    conversation.hidden = false;
    messageStatus.textContent = "";
    messageStatus.classList.remove("is-error");

    for (const button of contactsList.querySelectorAll(".contact-button")) {
        button.classList.toggle(
            "is-active",
            Number(button.dataset.contactId) === selectedContactId,
        );
    }

    loadConversation({initial: true});
    messageContent.focus();
}


async function sendMessage(event) {
    event.preventDefault();

    if (selectedContactId === null) {
        return;
    }

    const content = messageContent.value.trim();

    if (!content) {
        messageStatus.textContent = "Scrie un mesaj înainte de trimitere.";
        messageStatus.classList.add("is-error");
        return;
    }

    sendMessageButton.disabled = true;
    messageStatus.textContent = "Se trimite...";
    messageStatus.classList.remove("is-error");

    try {
        const response = await fetch(
            `/api/messages/conversations/${selectedContactId}`,
            {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({content}),
            },
        );
        const data = await readJsonResponse(response);

        appendMessages([data.message]);
        messageContent.value = "";
        messageCounter.textContent = "0 / 2000";
        messageStatus.textContent = "Mesaj trimis.";
        await loadContacts({quiet: true});
    } catch (error) {
        messageStatus.textContent = error.message;
        messageStatus.classList.add("is-error");
    } finally {
        sendMessageButton.disabled = false;
        messageContent.focus();
    }
}


async function initializeMessagesPage() {
    try {
        const response = await fetch("/api/auth/me");
        const data = await readJsonResponse(response);
        signedInUser.textContent = `Conectat ca ${data.user.username}`;
        await loadContacts();
    } catch (error) {
        showPageError(error.message);
    }
}


refreshContactsButton.addEventListener("click", () => loadContacts());
messageForm.addEventListener("submit", sendMessage);
messageContent.addEventListener("input", () => {
    messageCounter.textContent = `${messageContent.value.length} / 2000`;
});
messageContent.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        messageForm.requestSubmit();
    }
});

window.setInterval(() => {
    if (document.hidden) {
        return;
    }

    loadContacts({quiet: true});
    loadConversation({quiet: true});
}, 3000);

initializeMessagesPage();
