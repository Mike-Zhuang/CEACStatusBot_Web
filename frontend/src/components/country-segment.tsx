type ProfileCountry = "us" | "ca" | "kr";

interface CountrySegmentProps {
  country: ProfileCountry;
  setCountry: (country: ProfileCountry) => void;
  options: Array<{
    id: ProfileCountry;
    code: string;
    label: string;
    hint: string;
  }>;
}

export function CountrySegment(props: CountrySegmentProps) {
  const active = props.options.find((item) => item.id === props.country);
  return (
    <div className="country-segment-wrap">
      <div className="segmented country-segment" role="radiogroup">
        {props.options.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={props.country === option.id}
            className={props.country === option.id ? "selected" : ""}
            onClick={() => props.setCountry(option.id)}
          >
            {option.code}
          </button>
        ))}
      </div>
      {active && (
        <div className="country-segment-detail">
          <span className="country-segment-name">{active.label}</span>
          <span className="country-segment-hint">{active.hint}</span>
        </div>
      )}
    </div>
  );
}
