import { Landmark, Map, TreePine } from "lucide-react";
import type { LucideIcon } from "lucide-react";

type ProfileCountry = "us" | "ca" | "kr";

interface CountrySegmentProps {
  country: ProfileCountry;
  setCountry: (country: ProfileCountry) => void;
  groupLabel: string;
  options: Array<{
    id: ProfileCountry;
    code: string;
    label: string;
    hint: string;
  }>;
}

const countryIcons: Record<ProfileCountry, LucideIcon> = {
  us: Landmark,
  ca: TreePine,
  kr: Map,
};

export function CountrySegment(props: CountrySegmentProps) {
  return (
    <div className="country-choice" role="radiogroup" aria-label={props.groupLabel}>
      {props.options.map((option) => {
        const Icon = countryIcons[option.id];
        const isSelected = props.country === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={isSelected}
            className={`country-choice-item country-${option.id} ${isSelected ? "selected" : ""}`}
            onClick={() => props.setCountry(option.id)}
          >
            <span className="country-choice-mark" aria-hidden="true">
              <Icon size={22} strokeWidth={1.75} />
            </span>
            <span className="country-choice-copy">
              <span className="country-choice-heading">
                <span className="country-choice-code">{option.code}</span>
                <span className="country-choice-label">{option.label}</span>
              </span>
              <span className="country-choice-hint">{option.hint}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
