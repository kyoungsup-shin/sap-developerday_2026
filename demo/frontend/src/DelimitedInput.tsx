import { useEffect, useRef, useState } from "react";

/** Keep punctuation while typing; store a normalized list for contract validation. */
export default function DelimitedInput({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) {
  const [text, setText] = useState(value.join(", "));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(value.join(", ")); }, [value]);
  return <label className="harness-config__field">{label}<input value={text} onFocus={() => { focused.current = true; }} onBlur={() => { focused.current = false; setText(value.join(", ")); }} onChange={(event) => {
    setText(event.target.value); onChange(event.target.value.split(",").map((item) => item.trim()).filter(Boolean));
  }} /></label>;
}
