// Inject Upload Photo button onto challenge view page
console.log("Is this working");
(function() {
    console.log("Photo Evidence plugin script loaded");
    const container = document.querySelector(".challenge-description");
    if (!container) return;  // Safety check

    const challengeIdInput = document.querySelector("#challenge-id");
    if (!challengeIdInput) return;

    const challengeId = challengeIdInput.value;

/*
 * DISABLED: upload_button.js
 * This helper previously injected an upload link into pages. It's kept
 * here for reference but disabled so it does not run or get served to
 * clients by accident.

    const btn = document.createElement('a');
    btn.id = 'photo-upload-button';
    btn.className = 'btn btn-primary';
    btn.innerText = 'Upload Evidence';
    btn.href = `/photo_evidence/upload/${challengeId}`;
    if (target) target.appendChild(btn);

*/
})();
