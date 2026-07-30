function normalizeFilterText(value) {
    return String(value || "")
        .toLocaleLowerCase("tr-TR")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .trim();
}


function initializeEmailFilters() {
    const cards = Array.from(
        document.querySelectorAll("[data-filter-card]")
    );

    const searchInput =
        document.getElementById("emailSearch");

    const urgencyFilter =
        document.getElementById("urgencyFilter");

    const replyFilter =
        document.getElementById("replyFilter");

    const categoryFilter =
        document.getElementById("categoryFilter");

    const clearButton =
        document.getElementById("clearFiltersButton");

    const resultCount =
        document.getElementById("filterResultCount");

    const emptyState =
        document.getElementById("filterEmptyState");

    if (
        !cards.length
        || !searchInput
        || !urgencyFilter
        || !replyFilter
        || !categoryFilter
    ) {
        return;
    }

    const categories = [
        ...new Set(
            cards
                .map(
                    card =>
                        card.dataset.category || ""
                )
                .filter(Boolean)
        )
    ].sort(
        (first, second) =>
            first.localeCompare(
                second,
                "tr-TR"
            )
    );

    categories.forEach(category => {
        const option =
            document.createElement("option");

        option.value =
            normalizeFilterText(category);

        option.textContent =
            `📂 ${category}`;

        categoryFilter.appendChild(option);
    });


    function applyFilters() {
        const searchValue =
            normalizeFilterText(
                searchInput.value
            );

        const urgencyValue =
            urgencyFilter.value;

        const replyValue =
            replyFilter.value;

        const categoryValue =
            categoryFilter.value;

        let visibleCount = 0;

        cards.forEach(card => {
            const searchableText =
                normalizeFilterText(
                    card.dataset.search
                );

            const urgency =
                normalizeFilterText(
                    card.dataset.urgency
                );

            const category =
                normalizeFilterText(
                    card.dataset.category
                );

            const replyNeeded =
                card.dataset.replyNeeded
                === "true";

            const matchesSearch =
                !searchValue
                || searchableText.includes(
                    searchValue
                );

            const matchesUrgency =
                urgencyValue === "all"
                || urgency
                === normalizeFilterText(
                    urgencyValue
                );

            const matchesCategory =
                categoryValue === "all"
                || category
                === categoryValue;

            const matchesReply =
                replyValue === "all"
                || (
                    replyValue === "required"
                    && replyNeeded
                )
                || (
                    replyValue
                    === "not-required"
                    && !replyNeeded
                );

            const shouldShow =
                matchesSearch
                && matchesUrgency
                && matchesCategory
                && matchesReply;

            card.hidden = !shouldShow;

            if (shouldShow) {
                visibleCount += 1;
            }
        });

        document
            .querySelectorAll(
                "[data-date-group]"
            )
            .forEach(group => {
                const groupCards =
                    Array.from(
                        group.querySelectorAll(
                            "[data-filter-card]"
                        )
                    );

                const groupVisibleCount =
                    groupCards.filter(
                        card => !card.hidden
                    ).length;

                const groupCount =
                    group.querySelector(
                        "[data-group-count]"
                    );

                group.hidden =
                    groupVisibleCount === 0;

                if (groupCount) {
                    groupCount.textContent =
                        `${groupVisibleCount} e-posta`;
                }
            });

        if (resultCount) {
            resultCount.textContent =
                `${visibleCount} / `
                + `${cards.length} kayıt gösteriliyor`;
        }

        if (emptyState) {
            emptyState.hidden =
                visibleCount !== 0;
        }
    }


    [
        searchInput,
        urgencyFilter,
        replyFilter,
        categoryFilter
    ].forEach(control => {
        control.addEventListener(
            "input",
            applyFilters
        );

        control.addEventListener(
            "change",
            applyFilters
        );
    });


    clearButton?.addEventListener(
        "click",
        () => {
            searchInput.value = "";
            urgencyFilter.value = "all";
            replyFilter.value = "all";
            categoryFilter.value = "all";

            searchInput.focus();
            applyFilters();
        }
    );

    applyFilters();
}


document.addEventListener(
    "DOMContentLoaded",
    initializeEmailFilters
);


async function readJsonResponse(response) {
    const responseText =
        await response.text();

    try {
        return JSON.parse(responseText);

    } catch (error) {
        throw new Error(
            "Sunucu geçerli bir cevap döndürmedi."
        );
    }
}


function animateAndReload(emailCard) {
    emailCard.classList.add("removing");

    setTimeout(
        () => window.location.reload(),
        250
    );
}


async function generateReply(button) {
    const replySection =
        button.closest(".reply-section");

    const replyResult =
        replySection.querySelector(
            ".reply-result"
        );

    const replyText =
        replySection.querySelector(
            ".reply-text"
        );

    const toneSelect =
        replySection.querySelector(
            ".reply-tone-select"
        );

    const selectedTone =
        toneSelect?.value
        || "professional";

    const selectedToneLabel =
        toneSelect
            ?.selectedOptions[0]
            ?.textContent
            ?.trim()
        || "Profesyonel";

    const originalText =
        button.textContent.trim();

    button.disabled = true;

    if (toneSelect) {
        toneSelect.disabled = true;
    }

    button.textContent =
        "⏳ Cevap hazırlanıyor...";

    replyResult.hidden = false;

    replyText.textContent =
        `${selectedToneLabel} tonunda `
        + "cevap hazırlanıyor...";

    try {
        const response = await fetch(
            "/generate-reply",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    gmail_id:
                        button.dataset.gmailId,
                    sender:
                        button.dataset.sender,
                    subject:
                        button.dataset.subject,
                    snippet:
                        button.dataset.snippet,
                    summary:
                        button.dataset.summary,
                    tone:
                        selectedTone
                })
            }
        );

        const data =
            await readJsonResponse(response);

        if (
            !response.ok
            || !data.success
        ) {
            throw new Error(
                data.error
                || "Cevap taslağı oluşturulamadı."
            );
        }

        replyText.textContent =
            data.reply;

        button.textContent =
            "🔄 Seçilen Tonda Yeniden Oluştur";

    } catch (error) {
        replyText.textContent =
            `Hata: ${error.message}`;

        button.textContent =
            originalText;

    } finally {
        button.disabled = false;

        if (toneSelect) {
            toneSelect.disabled = false;
        }
    }
}


async function copyReply(button) {
    const replySection =
        button.closest(".reply-section");

    const replyText =
        replySection
            .querySelector(".reply-text")
            .textContent
            .trim();

    if (
        !replyText
        || replyText.startsWith("Hata:")
        || replyText.includes("hazırlıyor")
    ) {
        return;
    }

    try {
        await navigator.clipboard.writeText(
            replyText
        );

        const originalText =
            button.textContent;

        button.textContent =
            "✅ Kopyalandı";

        setTimeout(
            () => {
                button.textContent =
                    originalText;
            },
            1600
        );

    } catch (error) {
        button.textContent =
            "❌ Kopyalama başarısız";
    }
}


async function createGmailDraft(button) {
    const replySection =
        button.closest(".reply-section");

    const replyButton =
        replySection.querySelector(
            ".reply-button"
        );

    const replyText =
        replySection
            .querySelector(".reply-text")
            .textContent
            .trim();

    const statusBox =
        replySection.querySelector(
            ".draft-status"
        );

    if (
        !replyText
        || replyText.startsWith("Hata:")
        || replyText.includes("hazırlıyor")
    ) {
        window.alert(
            "Önce tamamlanmış bir "
            + "AI cevap taslağı oluşturun."
        );

        return;
    }

    if (!replyButton) {
        window.alert(
            "E-posta bilgileri bulunamadı."
        );

        return;
    }

    const originalText =
        button.textContent.trim();

    button.disabled = true;

    button.textContent =
        "⏳ Gmail taslağı oluşturuluyor...";

    if (statusBox) {
        statusBox.hidden = true;
        statusBox.className =
            "draft-status";
    }

    try {
        const response = await fetch(
            "/create-gmail-draft",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    sender:
                        replyButton.dataset.sender,
                    subject:
                        replyButton.dataset.subject,
                    thread_id:
                        replyButton.dataset.threadId
                        || "",
                    reply:
                        replyText
                })
            }
        );

        const data =
            await readJsonResponse(response);

        if (
            !response.ok
            || !data.success
        ) {
            throw new Error(
                data.error
                || "Gmail taslağı oluşturulamadı."
            );
        }

        button.textContent =
            "✅ Gmail Taslağı Kaydedildi";

        if (statusBox) {
            statusBox.textContent =
                "Taslak Gmail'e kaydedildi. "
                + `Alıcı: ${
                    data.recipient
                    || "belirlenemedi"
                }`;

            statusBox.classList.add(
                "success"
            );

            statusBox.hidden = false;
        }

        setTimeout(
            () => {
                button.textContent =
                    originalText;
            },
            2500
        );

    } catch (error) {
        button.textContent =
            originalText;

        if (statusBox) {
            statusBox.textContent =
                `Hata: ${error.message}`;

            statusBox.classList.add(
                "error"
            );

            statusBox.hidden = false;

        } else {
            window.alert(
                `Hata: ${error.message}`
            );
        }

    } finally {
        button.disabled = false;
    }
}


async function archiveEmail(button) {
    const confirmed =
        window.confirm(
            "Bu e-posta Gmail’de "
            + "arşivlenecek.\n\n"
            + "Gelen Kutusu’ndan kaldırılacak "
            + "fakat Tüm Postalar bölümünde "
            + "kalacak.\n\n"
            + "Ayrıca AI Email Analyzer "
            + "panelinden gizlenecek.\n\n"
            + "Devam edilsin mi?"
        );

    if (!confirmed) {
        return;
    }

    const emailCard =
        button.closest(".email-card");

    const originalText =
        button.textContent.trim();

    button.disabled = true;

    button.textContent =
        "⏳ Gmail’de arşivleniyor...";

    try {
        const response = await fetch(
            "/archive-email",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    gmail_id:
                        button.dataset.gmailId
                })
            }
        );

        const data =
            await readJsonResponse(response);

        if (
            !response.ok
            || !data.success
        ) {
            throw new Error(
                data.error
                || "E-posta arşivlenemedi."
            );
        }

        animateAndReload(emailCard);

    } catch (error) {
        window.alert(
            `Hata: ${error.message}`
        );

        button.disabled = false;

        button.textContent =
            originalText;
    }
}


async function hideEmail(button) {
    const confirmed =
        window.confirm(
            "Bu e-posta yalnızca "
            + "AI Email Analyzer panelinden "
            + "gizlenecek.\n\n"
            + "Gmail hesabındaki asıl e-posta "
            + "değiştirilmeyecek.\n\n"
            + "Devam edilsin mi?"
        );

    if (!confirmed) {
        return;
    }

    const emailCard =
        button.closest(".email-card");

    const originalText =
        button.textContent.trim();

    button.disabled = true;

    button.textContent =
        "⏳ Gizleniyor...";

    try {
        const response = await fetch(
            "/hide-email",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    gmail_id:
                        button.dataset.gmailId
                })
            }
        );

        const data =
            await readJsonResponse(response);

        if (
            !response.ok
            || !data.success
        ) {
            throw new Error(
                data.error
                || "E-posta gizlenemedi."
            );
        }

        animateAndReload(emailCard);

    } catch (error) {
        window.alert(
            `Hata: ${error.message}`
        );

        button.disabled = false;

        button.textContent =
            originalText;
    }
}


async function restoreEmail(button) {
    const confirmed =
        window.confirm(
            "Bu mesaj yalnızca "
            + "AI Email Analyzer paneline "
            + "geri getirilecek.\n\n"
            + "Gmail’de arşivlenmişse "
            + "Gelen Kutusu’na taşınmayacak.\n\n"
            + "Devam edilsin mi?"
        );

    if (!confirmed) {
        return;
    }

    const emailCard =
        button.closest(".email-card");

    const originalText =
        button.textContent.trim();

    button.disabled = true;

    button.textContent =
        "⏳ Panele getiriliyor...";

    try {
        const response = await fetch(
            "/restore-email",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    gmail_id:
                        button.dataset.gmailId
                })
            }
        );

        const data =
            await readJsonResponse(response);

        if (
            !response.ok
            || !data.success
        ) {
            throw new Error(
                data.error
                || "E-posta geri getirilemedi."
            );
        }

        animateAndReload(emailCard);

    } catch (error) {
        window.alert(
            `Hata: ${error.message}`
        );

        button.disabled = false;

        button.textContent =
            originalText;
    }
}


async function restoreToInbox(button) {
    const confirmed =
        window.confirm(
            "Bu e-posta Gmail Gelen Kutusu’na "
            + "ve AI Email Analyzer paneline "
            + "geri getirilecek.\n\n"
            + "Devam edilsin mi?"
        );

    if (!confirmed) {
        return;
    }

    const emailCard =
        button.closest(".email-card");

    const originalText =
        button.textContent.trim();

    button.disabled = true;

    button.textContent =
        "⏳ Gelen Kutusu’na taşınıyor...";

    try {
        const response = await fetch(
            "/restore-to-inbox",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    gmail_id:
                        button.dataset.gmailId
                })
            }
        );

        const data =
            await readJsonResponse(response);

        if (
            !response.ok
            || !data.success
        ) {
            throw new Error(
                data.error
                || "E-posta Gelen Kutusu’na "
                + "taşınamadı."
            );
        }

        animateAndReload(emailCard);

    } catch (error) {
        window.alert(
            `Hata: ${error.message}`
        );

        button.disabled = false;

        button.textContent =
            originalText;
    }
}