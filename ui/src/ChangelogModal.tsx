import "./ChangelogModal.css";
import { RELEASES } from "./releases";

export default function ChangelogModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal changelog-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>What's new</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="changelog-body">
          {RELEASES.map((r) => (
            <div key={r.version} className="changelog-release">
              <div className="changelog-release-header">
                <span className="changelog-version">v{r.version}</span>
                <span className="changelog-date">{r.date}</span>
              </div>
              {r.added && (
                <ul className="changelog-list">
                  {r.added.map((item) => (
                    <li key={item}>
                      <span className="changelog-tag added">Added</span>
                      {item}
                    </li>
                  ))}
                </ul>
              )}
              {r.changed && (
                <ul className="changelog-list">
                  {r.changed.map((item) => (
                    <li key={item}>
                      <span className="changelog-tag changed">Changed</span>
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
