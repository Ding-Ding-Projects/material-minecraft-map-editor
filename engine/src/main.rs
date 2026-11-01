fn main() {
    let options =
        match material_world_engine::reference::Options::parse(std::env::args_os().skip(1)) {
            Ok(v) => v,
            Err(_) => {
                eprintln!("Invalid reference startup options");
                std::process::exit(2);
            }
        };
    let reference = material_world_engine::reference::Availability::load(options);
    if material_world_engine::protocol::serve_with_reference(
        std::io::stdin().lock(),
        std::io::stdout().lock(),
        &reference,
    )
    .is_err()
    {
        eprintln!("Engine protocol transport stopped");
        std::process::exit(1);
    }
}
