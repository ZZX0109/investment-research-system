import { Languages } from "lucide-react";
import { useI18n, type UiLanguage } from "../i18n";

export function LanguageSwitch() {
  const { language, setLanguage, t } = useI18n();
  const options: Array<[UiLanguage, string]> = [["zh-CN", t("language.chinese")], ["en-US", t("language.english")]];
  return (
    <div className="language-switch" role="group" aria-label={t("language.label")}>
      <Languages size={15} aria-hidden="true" />
      {options.map(([value, label]) => (
        <button
          key={value}
          className={`language-switch__button ${language === value ? "language-switch__button--active" : ""}`}
          type="button"
          onClick={() => setLanguage(value)}
          aria-pressed={language === value}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
