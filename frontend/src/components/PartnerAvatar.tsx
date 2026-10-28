import type { CSSProperties } from "react";
import { partnerHue, partnerInitials } from "../format";

export function PartnerAvatar({ partnerId, size = 32 }: { partnerId: string; size?: number }) {
  const style = {
    "--hue": partnerHue(partnerId),
    width: size,
    height: size,
    fontSize: size * 0.38,
  } as CSSProperties;
  return (
    <span className="avatar" style={style} title={partnerId}>
      {partnerInitials(partnerId)}
    </span>
  );
}
