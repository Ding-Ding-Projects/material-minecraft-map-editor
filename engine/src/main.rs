fn main() {
    if material_world_engine::protocol::serve(std::io::stdin().lock(), std::io::stdout().lock())
        .is_err()
    {
        eprintln!("Engine protocol transport stopped");
        std::process::exit(1);
    }
}
