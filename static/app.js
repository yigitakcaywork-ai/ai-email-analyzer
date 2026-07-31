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

        window.updateBulkSelection?.({
            clearHiddenSelections: true
        });
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

function initializeBulkActions() {
    const checkboxes = Array.from(
        document.querySelectorAll(
            ".email-select-checkbox"
        )
    );

    const selectVisibleCheckbox =
        document.getElementById(
            "selectVisibleEmails"
        );

    const actionBar =
        document.getElementById(
            "bulkActionBar"
        );

    const selectedCount =
        document.getElementById(
            "bulkSelectedCount"
        );

    const archiveButton =
        document.getElementById(
            "bulkArchiveButton"
        );

    const hideButton =
        document.getElementById(
            "bulkHideButton"
        );

    const clearButton =
        document.getElementById(
            "clearBulkSelectionButton"
        );

    const statusBox =
        document.getElementById(
            "bulkActionStatus"
        );

    if (
        !checkboxes.length
        || !selectVisibleCheckbox
        || !actionBar
    ) {
        return;
    }

    const visibleCheckboxes = () =>
        checkboxes.filter(checkbox => {
            const card = checkbox.closest(
                "[data-filter-card]"
            );

            return card && !card.hidden;
        });

    const checkedCheckboxes = () =>
        checkboxes.filter(
            checkbox => checkbox.checked
        );

    const setBusy = isBusy => {
        checkboxes.forEach(checkbox => {
            checkbox.disabled = isBusy;
        });

        selectVisibleCheckbox.disabled =
            isBusy;

        [archiveButton, hideButton, clearButton]
            .filter(Boolean)
            .forEach(button => {
                button.disabled = isBusy;
            });
    };

    const showStatus = (message, type) => {
        if (!statusBox) {
            return;
        }

        statusBox.textContent = message;
        statusBox.className =
            `bulk-action-status ${type}`;
        statusBox.hidden = false;
    };

    window.updateBulkSelection = (options = {}) => {
        if (options.clearHiddenSelections) {
            checkboxes.forEach(checkbox => {
                const card = checkbox.closest(
                    "[data-filter-card]"
                );

                if (card?.hidden) {
                    checkbox.checked = false;
                    card.classList.remove(
                        "selected"
                    );
                }
            });
        }

        checkboxes.forEach(checkbox => {
            checkbox
                .closest(".email-card")
                ?.classList.toggle(
                    "selected",
                    checkbox.checked
                );
        });

        const selected = checkedCheckboxes();
        const visible = visibleCheckboxes();
        const selectedVisibleCount =
            visible.filter(
                checkbox => checkbox.checked
            ).length;

        actionBar.hidden = selected.length === 0;

        if (selectedCount) {
            selectedCount.textContent =
                `${selected.length} e-posta seçildi`;
        }

        selectVisibleCheckbox.checked =
            visible.length > 0
            && selectedVisibleCount
            === visible.length;

        selectVisibleCheckbox.indeterminate =
            selectedVisibleCount > 0
            && selectedVisibleCount
            < visible.length;
    };

    selectVisibleCheckbox.addEventListener(
        "change",
        () => {
            visibleCheckboxes().forEach(
                checkbox => {
                    checkbox.checked =
                        selectVisibleCheckbox.checked;
                }
            );

            window.updateBulkSelection();
        }
    );

    checkboxes.forEach(checkbox => {
        checkbox.addEventListener(
            "change",
            () => window.updateBulkSelection()
        );
    });

    clearButton?.addEventListener(
        "click",
        () => {
            checkboxes.forEach(checkbox => {
                checkbox.checked = false;
            });

            if (statusBox) {
                statusBox.hidden = true;
            }

            window.updateBulkSelection();
        }
    );

    async function runBulkAction({
        endpoint,
        confirmationMessage,
        busyText,
        button
    }) {
        const selected = checkedCheckboxes();
        const gmailIds = selected.map(
            checkbox => checkbox.value
        );

        if (!gmailIds.length) {
            return;
        }

        if (!window.confirm(confirmationMessage)) {
            return;
        }

        const originalText =
            button.textContent.trim();

        setBusy(true);
        button.textContent = busyText;

        if (statusBox) {
            statusBox.hidden = true;
        }

        try {
            const response = await fetch(
                endpoint,
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify({
                        gmail_ids: gmailIds
                    })
                }
            );

            const data =
                await readJsonResponse(response);

            const completedIds = new Set(
                data.completed_ids || []
            );

            checkboxes.forEach(checkbox => {
                if (completedIds.has(checkbox.value)) {
                    checkbox
                        .closest(".email-card")
                        ?.classList.add("removing");
                }
            });

            if (!response.ok && !completedIds.size) {
                throw new Error(
                    data.error
                    || "Toplu işlem tamamlanamadı."
                );
            }

            const failedCount =
                Number(data.failed_count || 0);

            if (failedCount > 0) {
                showStatus(
                    `${data.completed_count || 0} işlem tamamlandı, `
                    + `${failedCount} işlem başarısız oldu.`,
                    "warning"
                );

                setTimeout(
                    () => window.location.reload(),
                    1500
                );
            } else {
                showStatus(
                    data.message
                    || "Toplu işlem tamamlandı.",
                    "success"
                );

                setTimeout(
                    () => window.location.reload(),
                    500
                );
            }

        } catch (error) {
            showStatus(
                `Hata: ${error.message}`,
                "error"
            );

            setBusy(false);
            button.textContent = originalText;
        }
    }

    archiveButton?.addEventListener(
        "click",
        () => runBulkAction({
            endpoint: "/bulk-archive-emails",
            confirmationMessage:
                `${checkedCheckboxes().length} e-posta `
                + "Gmail'de arşivlenecek ve panelden "
                + "gizlenecek. Devam edilsin mi?",
            busyText: "⏳ Arşivleniyor...",
            button: archiveButton
        })
    );

    hideButton?.addEventListener(
        "click",
        () => runBulkAction({
            endpoint: "/bulk-hide-emails",
            confirmationMessage:
                `${checkedCheckboxes().length} e-posta `
                + "yalnızca panelden gizlenecek. "
                + "Gmail mesajları değişmeyecek. "
                + "Devam edilsin mi?",
            busyText: "⏳ Gizleniyor...",
            button: hideButton
        })
    );

    window.updateBulkSelection();
}


document.addEventListener(
    "DOMContentLoaded",
    initializeBulkActions
);
