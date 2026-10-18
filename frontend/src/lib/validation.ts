export type RegistrationDraft = {
  full_name: string;
  phone_number: string;
  address: string;
  slot_id: string;
  guest_count: string;
};

export type RegistrationPayload = {
  full_name: string;
  phone_number: string;
  address: string;
  slot_id: string;
  guest_count: number;
  idempotency_key: string;
};

const trim = (value: string) => value.trim();

export function validateStepOne(form: RegistrationDraft): string | null {
  const fullName = trim(form.full_name);
  const phone = trim(form.phone_number);
  const address = trim(form.address);
  if (fullName.length < 2 || fullName.length > 160) return "Full name must contain 2 to 160 characters.";
  if (phone.length < 5 || phone.length > 40) return "Phone number must contain 5 to 40 characters.";
  if (address.length < 3 || address.length > 2000) return "Address must contain 3 to 2,000 characters.";
  return null;
}

export function validateStepTwo(form: RegistrationDraft, maximum: number): string | null {
  const guestCount = Number(form.guest_count);
  if (!trim(form.slot_id)) return "Choose a time slot.";
  if (!Number.isSafeInteger(guestCount) || guestCount < 1 || guestCount > maximum) return `Guest count must be a whole number from 1 to ${maximum}.`;
  return null;
}

export function toRegistrationPayload(form: RegistrationDraft): RegistrationPayload {
  return {
    full_name: trim(form.full_name),
    phone_number: trim(form.phone_number),
    address: trim(form.address),
    slot_id: trim(form.slot_id),
    guest_count: Number(form.guest_count),
    idempotency_key: crypto.randomUUID(),
  };
}

export function validateAdminToken(token: string): string | null {
  return trim(token) ? null : "Admin token is required.";
}

