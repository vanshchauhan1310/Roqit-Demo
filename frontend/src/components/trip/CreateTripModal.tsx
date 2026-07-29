import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { createTrip } from "@/api/trips";

interface CreateTripModalProps {
  open: boolean;
  onClose: () => void;
}

export function CreateTripModal({ open, onClose }: CreateTripModalProps) {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => createTrip({ origin, destination }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Create Trip">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <div>
          <label className="block text-sm text-gray-600 mb-1">Origin</label>
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm text-gray-600 mb-1">Destination</label>
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create Trip"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
