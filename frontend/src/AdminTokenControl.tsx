import { useState } from "react";

type Props = { onSaved: () => void };

export function AdminTokenControl({ onSaved }: Props) {
  const [value, setValue] = useState(() => sessionStorage.getItem("lyra-hub-admin-token") ?? "");
  const [saved, setSaved] = useState(false);

  function save() {
    if (value.trim()) sessionStorage.setItem("lyra-hub-admin-token", value.trim());
    else sessionStorage.removeItem("lyra-hub-admin-token");
    setSaved(true);
    onSaved();
  }

  return (
    <section className="section adminAccessPanel">
      <div>
        <h3>平台管理员访问</h3>
        <p>令牌仅保存在当前浏览器会话中，所有管理请求由 Hub 后端代发。</p>
      </div>
      <div className="adminTokenInput">
        <label>
          管理令牌
          <input
            aria-label="平台管理令牌"
            autoComplete="off"
            onChange={(event) => { setValue(event.target.value); setSaved(false); }}
            placeholder="输入 Hub 管理令牌"
            type="password"
            value={value}
          />
        </label>
        <button className="secondaryButton" onClick={save} type="button">保存到当前会话</button>
        {saved && <span role="status">已保存到当前会话</span>}
      </div>
    </section>
  );
}
