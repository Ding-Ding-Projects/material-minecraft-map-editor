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
    let session = material_world_engine::terrain::Session::new(reference);
    if let Err(error) =
        material_world_engine::terrain::serve(std::io::stdin(), std::io::stdout().lock(), session)
    {
        if error.kind() == std::io::ErrorKind::TimedOut {
            eprintln!("Engine terrain session timed out");
            std::process::exit(3);
        }
        eprintln!("Engine protocol transport stopped");
        std::process::exit(1);
    }
}
