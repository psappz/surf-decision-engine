document.addEventListener('DOMContentLoaded', () => {
  const modal = document.querySelector('[data-provider-modal]');
  if (!modal) return;
  const title = modal.querySelector('[data-modal-title]');
  const status = modal.querySelector('[data-modal-status]');
  const reason = modal.querySelector('[data-modal-reason]');
  const fetched = modal.querySelector('[data-modal-fetched]');
  const rate = modal.querySelector('[data-modal-rate]');
  const data = modal.querySelector('[data-modal-data]');
  const close = () => { modal.classList.remove('is-open'); modal.setAttribute('aria-hidden', 'true'); };
  const open = (button) => {
    title.textContent = button.dataset.providerName || 'Provider';
    status.textContent = button.dataset.providerStatus || '';
    status.className = 'status-pill ' + (button.dataset.providerStatus || '').toLowerCase();
    reason.textContent = button.dataset.providerReason || '';
    fetched.textContent = button.dataset.providerFetched || '';
    rate.textContent = button.dataset.providerRate || '';
    data.innerHTML = '';
    (button.dataset.providerData || 'No data available.').split('||').forEach(line => {
      const li = document.createElement('li'); li.textContent = line; data.appendChild(li);
    });
    modal.classList.add('is-open'); modal.setAttribute('aria-hidden', 'false'); modal.querySelector('.modal-close').focus();
  };
  document.querySelectorAll('[data-provider-button]').forEach(btn => btn.addEventListener('click', () => open(btn)));
  modal.querySelector('.modal-close').addEventListener('click', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.classList.contains('is-open')) close(); });
});
