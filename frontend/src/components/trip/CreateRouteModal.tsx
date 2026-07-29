import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { createRoute } from "@/api/routes";

interface CreateRouteModalProps {
  open: boolean;
  onClose: () => void;
  tripId?: string;
}

export function CreateRouteModal({ open, onClose, tripId }: CreateRouteModalProps) {
  const [name, setName] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => createRoute({ trip_id: tripId, name, stops: [] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      onClose();
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Create Route">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <div>
          <label className="block text-sm text-gray-600 mb-1">Route Name</label>
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create Route"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
