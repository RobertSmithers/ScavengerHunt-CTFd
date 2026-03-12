document.addEventListener("DOMContentLoaded", () => {
  function attachHandlers() {
    document.querySelectorAll("form[action*='/api/v1/photo_challenges/admin/review/']").forEach((f) => {
      f.removeEventListener('submit', handleForm);
      f.addEventListener('submit', handleForm);
    });
  }

  function showAdminNotice(message, type='success') {
    const container = document.querySelector('.container');
    if (!container) return;
    const notice = document.createElement('div');
    notice.className = `alert alert-${type} mt-3`;
    notice.textContent = message;
    container.prepend(notice);
    setTimeout(()=> notice.remove(), 3000);
  }

  function handleForm(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const url = form.action;
    const formData = new FormData(form);

    fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: formData,
      credentials: "same-origin",
    })
      .then((r) => r.json())
      .then((data) => {
        if (data && data.html) {
          // Parse returned HTML and replace only the affected <tr> for the
          // submission_id so we don't flash the whole page.
          const parser = new DOMParser();
          const doc = parser.parseFromString(data.html, "text/html");
          const newRow = Array.from(doc.querySelectorAll('tbody tr')).find(r => {
            const idCell = r.querySelector('td');
            return idCell && idCell.textContent.trim() === String(data.submission_id);
          });
          if (newRow) {
            // find the old row in the current DOM
            const oldRow = Array.from(document.querySelectorAll('tbody tr')).find(r => {
              const idCell = r.querySelector('td');
              return idCell && idCell.textContent.trim() === String(data.submission_id);
            });
            if (oldRow) {
              oldRow.replaceWith(newRow);
              // highlight the updated row
              const highlightColor = data.status === 'approved' ? '#d4edda' : (data.status === 'rejected' ? '#f8d7da' : '#fff3cd');
              newRow.style.transition = 'background-color 0.3s ease';
              newRow.style.backgroundColor = highlightColor;
              setTimeout(() => { newRow.style.backgroundColor = ''; }, 2500);
              // Re-attach handlers to remaining forms
              attachHandlers();
            } else {
              // fallback: replace whole container
              const newContainer = doc.querySelector('.container');
              const oldContainer = document.querySelector('.container');
              if (newContainer && oldContainer) {
                oldContainer.replaceWith(newContainer);
                attachHandlers();
              } else {
                window.location.reload();
              }
            }
          } else {
            // fallback behavior: reload so UI matches server
            window.location.reload();
          }
        } else if (data && data.success) {
          showAdminNotice('Action completed', 'success');
          window.location.reload();
        } else {
          window.location.reload();
        }
      })
      .catch(() => {
        window.location.reload();
      });
  }

  // Initial attach
  attachHandlers();
});
